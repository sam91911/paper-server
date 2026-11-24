"""Enroll an AI identity, call the library API, and import public PDFs."""

import argparse
import base64
import getpass
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .paper_source import fetch_pdf
from .review import LibraryClient, LibraryError, PDF_LIMIT, library_origin

USERNAME = r"[A-Za-z0-9][A-Za-z0-9_.-]{1,31}"
REGISTRATION_PATH = re.compile(r"/api/ai/register/[A-Za-z0-9_-]{43}")


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class AgentClient(LibraryClient):
    def __init__(self, port, username, private_key, *, server_url=None):
        super().__init__(port, None, server_url=server_url)
        self.username = username
        self.private_key = private_key
        self.renew_at = 0

    @classmethod
    def from_identity(cls, path):
        with path.open(encoding="utf-8") as stream:
            if os.name == "posix" and os.fstat(stream.fileno()).st_mode & 0o077:
                raise ValueError("Set private identity file permissions to 600.")
            data = json.load(stream)
        username, key = data["username"], data["private_key"]
        if not re.fullmatch(USERNAME, username) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", key):
            raise ValueError("The AI identity file is invalid.")
        server_url = data.get("server_url") or f"http://127.0.0.1:{data['port']}"
        return cls(None, username, Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(key + "=")),
                   server_url=server_url)

    def sign(self, action, username, value):
        return encode(self.private_key.sign(f"paper-library:{action}:{username}:{value}".encode("ascii")))

    def authorize(self):
        if self.key is None or time.monotonic() >= self.renew_at:
            self.key = None
            challenge = json.loads(super().request("/api/ai/challenge", {"username": self.username}))
            start = time.monotonic()
            value = challenge["challenge"]
            session = json.loads(super().request("/api/ai/login", {
                "username": self.username, "challenge": value,
                "signature": self.sign("login", challenge["username"], value),
            }))
            self.renew_at = start + session["expires_in"] - 10
            self.key = session["access_token"]

    def request(self, route, data=None, *, limit=1_000_000):
        self.authorize()
        return super().request(route, data, limit=limit)

    def upload_pdf(self, filename, payload, recipients):
        self.authorize()
        return json.loads(self._send("/api/papers", payload, {
            "Content-Type": "application/pdf",
            "X-Paper-Filename": quote(filename, safe=""),
            "X-Paper-Audience": "owner",
            "X-Paper-Recipients": quote(json.dumps(recipients), safe=""),
        }))


def import_paper(client, url, filename, recipients):
    if len(recipients) > 50 or any(not re.fullmatch(USERNAME, name) for name in recipients):
        raise ValueError("Provide up to 50 valid recipient usernames.")
    if filename and (not filename.lower().endswith(".pdf") or "/" in filename or "\\" in filename
                     or any(ord(char) < 32 for char in filename) or len(filename.encode()) > 240):
        raise ValueError("Use a .pdf filename without directory separators, up to 240 bytes.")
    source_name, payload = fetch_pdf(url, PDF_LIMIT)
    return client.upload_pdf(filename or source_name, payload, recipients)


def send_heartbeats(client, *, once=False):
    interval = 60
    announced = False
    while True:
        try:
            receipt = json.loads(client.request("/api/ai/heartbeat", {}))
            interval = receipt["interval_seconds"]
            if not announced:
                print(json.dumps(receipt), flush=True)
                announced = True
            if once:
                return
        except (OSError, LibraryError) as error:
            if once or (isinstance(error, LibraryError) and error.status < 500 and error.status != 429):
                raise
            print(f"Heartbeat failed. Retrying in {interval} seconds.", file=sys.stderr)
        time.sleep(interval)


def register(identity, username, url):
    parsed = urlsplit(url)
    route = parsed.path
    if not REGISTRATION_PATH.fullmatch(route) or "?" in url or "#" in url:
        raise ValueError("Enter the one-time AI registration URL.")
    origin = library_origin(f"{parsed.scheme}://{parsed.netloc}")
    if not re.fullmatch(USERNAME, username):
        raise ValueError("Enter the exact invited username.")
    identity.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not identity.exists():
        private_key = Ed25519PrivateKey.generate()
        stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=identity.parent, delete=False)
        try:
            with stream:
                json.dump({"username": username, "server_url": origin,
                           "private_key": encode(private_key.private_bytes_raw())}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(stream.name, identity)
            except FileExistsError:
                pass  # A concurrent enrollment saved an identity first.
        finally:
            Path(stream.name).unlink()
    # Reuse the original key if enrollment was interrupted.
    agent = AgentClient.from_identity(identity)
    if agent.username != username or agent.base != origin:
        raise ValueError("Choose a different identity file for this username or library URL.")
    client = LibraryClient(None, None, server_url=origin)
    return json.loads(client.request(route, {
        "public_key": encode(agent.private_key.public_key().public_bytes_raw()),
        "signature": agent.sign("register", username, route),
    }))["account"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("register", help="Enroll with a one-time URL entered privately or passed through stdin")
    enroll.add_argument("--identity", type=Path, required=True)
    enroll.add_argument("--username", required=True)
    request = commands.add_parser("request", help="Sign in and call a library endpoint")
    request.add_argument("--identity", type=Path, required=True)
    request.add_argument("route", help="Path and optional query, such as /api/account")
    request.add_argument("--json-stdin", action="store_true", help="Read a JSON request body from stdin and send POST")
    paper = commands.add_parser("import-paper", help="Fetch a public HTTPS PDF and upload it to your library")
    paper.add_argument("--identity", type=Path, required=True)
    paper.add_argument("--url", required=True, help="Direct public HTTPS PDF URL")
    paper.add_argument("--filename", help="Filename to use in the library")
    paper.add_argument("--recipient", action="append", default=[], help="Share with this username (repeatable)")
    heartbeat = commands.add_parser("heartbeat", help="Report presence to your enrolled library")
    heartbeat.add_argument("--identity", type=Path, required=True)
    heartbeat.add_argument("--once", action="store_true", help="Send one heartbeat and exit")
    args = parser.parse_args()
    try:
        if args.command == "register":
            url = getpass.getpass("One-time registration URL: ") if sys.stdin.isatty() else sys.stdin.readline().strip()
            account = register(args.identity.expanduser(), args.username, url)
            print(f"Registered {account['username']} ({account['role']}).")
        elif args.command == "import-paper":
            client = AgentClient.from_identity(args.identity.expanduser())
            print(json.dumps(import_paper(client, args.url, args.filename, args.recipient)))
        elif args.command == "heartbeat":
            client = AgentClient.from_identity(args.identity.expanduser())
            try:
                send_heartbeats(client, once=args.once)
            except KeyboardInterrupt:
                return
        else:
            if not args.route.startswith("/") or args.route.startswith("//") or "#" in args.route:
                raise ValueError("Enter a library path such as /api/account.")
            data = json.load(sys.stdin) if args.json_stdin else None
            if args.json_stdin and not isinstance(data, dict):
                raise ValueError("Enter a JSON object.")
            client = AgentClient.from_identity(args.identity.expanduser())
            sys.stdout.buffer.write(client.request(args.route, data, limit=PDF_LIMIT))
    except (OSError, ValueError, KeyError, TypeError, EOFError) as error:
        parser.exit(1, f"Library agent: {error}\n")


if __name__ == "__main__":
    main()
