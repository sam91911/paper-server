"""Enroll an AI identity, call the library API, and import public PDFs."""

import argparse
import base64
import getpass
import json
import os
import re
import signal
import subprocess
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
PAPER_AUDIENCES = ("owner", "users", "local", "all", "ai")
ARTIFACT_LIMIT = 100 * 1024 * 1024
ARTIFACT_KINDS = ("code", "data", "environment", "equipment", "tool_record")


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

    def upload_pdf(self, filename, payload, recipients, *, audience="owner"):
        self.authorize()
        return json.loads(self._send("/api/papers", payload, {
            "Content-Type": "application/pdf",
            "X-Paper-Filename": quote(filename, safe=""),
            "X-Paper-Audience": audience,
            "X-Paper-Recipients": quote(json.dumps(recipients), safe=""),
        }))

    def upload_artifact(self, metadata, payload):
        self.authorize()
        return json.loads(self._send("/api/research-upload", payload, {
            "Content-Type": "application/octet-stream",
            "X-Research-Metadata": quote(json.dumps(metadata), safe=""),
        }))


def import_paper(client, url, filename, recipients, *, audience="owner"):
    if audience not in PAPER_AUDIENCES:
        raise ValueError("Choose a valid paper audience.")
    if len(recipients) > 50 or any(not re.fullmatch(USERNAME, name) for name in recipients):
        raise ValueError("Provide up to 50 valid recipient usernames.")
    if filename and (not filename.lower().endswith(".pdf") or "/" in filename or "\\" in filename
                     or any(ord(char) < 32 for char in filename) or len(filename.encode()) > 240):
        raise ValueError("Use a .pdf filename without directory separators, up to 240 bytes.")
    source_name, payload = fetch_pdf(url, PDF_LIMIT)
    return client.upload_pdf(filename or source_name, payload, recipients, audience=audience)


def read_artifact(stream):
    payload = stream.read(ARTIFACT_LIMIT + 1)
    if len(payload) > ARTIFACT_LIMIT:
        raise ValueError("Choose an artifact of up to 100 MiB.")
    return payload


def upload_artifact(client, args):
    metadata = {"experiment_id": args.experiment_id, "run_id": args.run_id,
                "title": args.title, "description": args.description, "audience": args.audience}
    if (args.item_id is None) != (args.item_revision is None):
        raise ValueError("Provide both the item ID and item revision when uploading a new version.")
    if args.item_id is not None:
        metadata.update(id=args.item_id, revision=args.item_revision)
    if args.repository is not None:
        if args.kind not in (None, "code"):
            raise ValueError("A Git snapshot is a code artifact.")
        git = ["git", "-C", str(args.repository.expanduser())]
        try:
            commit = subprocess.check_output(
                [*git, "rev-parse", "--verify", "--end-of-options", f"{args.commit}^{{commit}}"],
                text=True, timeout=15, stderr=subprocess.DEVNULL,
            ).strip()
            with tempfile.TemporaryFile() as stream:
                subprocess.run([*git, "archive", "--format=zip", commit], stdout=stream,
                               stderr=subprocess.DEVNULL, check=True, timeout=120)
                stream.seek(0)
                payload = read_artifact(stream)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise ValueError("Could not archive the selected local Git commit.") from error
        metadata.update(kind="code", filename=f"{commit[:12]}.zip",
                        description=f"Git commit {commit}.\n{args.description}".rstrip())
    else:
        with args.file.expanduser().open("rb") as stream:
            payload = read_artifact(stream)
        metadata.update(kind=args.kind or "data", filename=args.file.name)
    return client.upload_artifact(metadata, payload)


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


def run_scheduled_command(command, identity, run_id, timeout):
    if timeout <= 0:
        return False, "The run lease expired before the command started."
    try:
        with subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=os.name == "posix",
                              env={**os.environ, "PAPER_AGENT_IDENTITY": str(identity.resolve()),
                                   "PAPER_AGENT_RUN_ID": run_id}) as process:
            try:
                code = process.wait(timeout=timeout)
            except (KeyboardInterrupt, subprocess.TimeoutExpired) as error:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.wait()
                if isinstance(error, KeyboardInterrupt):
                    raise
                return False, "The research command timed out."
    except OSError:
        return False, "Could not start the configured research command."
    return code == 0, f"Research command exited with status {code}."


def run_schedule(client, identity, command, *, once=False):
    route = "/api/agent-schedules"
    completion = None
    while True:
        try:
            if completion is not None:
                client.request(route, completion)
                completion = None
                if once:
                    return
            client.request("/api/ai/heartbeat", {})
            started = time.monotonic()
            run = json.loads(client.request(route, {"action": "claim"}))["run"]
            if run is not None:
                timeout = run["timeout_seconds"] - (time.monotonic() - started) - 5
                try:
                    success, detail = run_scheduled_command(command, identity, run["id"], timeout)
                except KeyboardInterrupt:
                    try:
                        client.request(route, {"action": "finish", "id": run["id"], "success": False,
                                               "detail": "Runner interrupted."})
                    except (OSError, LibraryError):
                        print("Could not report the interrupted run.", file=sys.stderr)
                    raise
                completion = {"action": "finish", "id": run["id"], "success": success, "detail": detail}
                continue
            if once:
                return
        except (OSError, LibraryError) as error:
            if completion and isinstance(error, LibraryError) and error.status == 409:
                completion = None
                if once:
                    raise
            elif once or (isinstance(error, LibraryError) and error.status < 500 and error.status != 429):
                raise
            print("Schedule check failed. Retrying in 30 seconds.", file=sys.stderr)
        time.sleep(30)


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
    paper.add_argument("--audience", choices=PAPER_AUDIENCES, default="owner", help="Paper audience (default: owner)")
    paper.add_argument("--recipient", action="append", default=[], help="Share with this username (repeatable)")
    artifact = commands.add_parser("upload-artifact", help="Submit a local file or a committed Git snapshot")
    artifact.add_argument("--identity", type=Path, required=True)
    artifact.add_argument("--experiment-id", type=int, required=True)
    artifact.add_argument("--run-id", type=int)
    artifact.add_argument("--title", required=True)
    artifact.add_argument("--description", default="")
    artifact.add_argument("--kind", choices=ARTIFACT_KINDS)
    artifact.add_argument("--audience", choices=PAPER_AUDIENCES, default="owner")
    artifact.add_argument("--item-id", type=int)
    artifact.add_argument("--item-revision", type=int)
    source = artifact.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--repository", type=Path)
    artifact.add_argument("--commit", default="HEAD", help="Git commit or ref for --repository (default: HEAD)")
    heartbeat = commands.add_parser("heartbeat", help="Report presence to your enrolled library")
    heartbeat.add_argument("--identity", type=Path, required=True)
    heartbeat.add_argument("--once", action="store_true", help="Send one heartbeat and exit")
    runner = commands.add_parser("run-schedule", help="Execute due research using a locally configured command")
    runner.add_argument("--identity", type=Path, required=True)
    runner.add_argument("--once", action="store_true", help="Check for and execute at most one due run")
    runner.add_argument("runner_command", nargs=argparse.REMAINDER, help="Local command and arguments after --")
    git_header = commands.add_parser("git-header", help="Generate a short-lived Git authorization header")
    git_header.add_argument("--identity", type=Path, required=True)
    git_header.add_argument("--server-url", required=True, help="Confirm the destination library origin")
    args = parser.parse_args()
    try:
        if args.command == "register":
            url = getpass.getpass("One-time registration URL: ") if sys.stdin.isatty() else sys.stdin.readline().strip()
            account = register(args.identity.expanduser(), args.username, url)
            print(f"Registered {account['username']} ({account['role']}).")
        elif args.command == "import-paper":
            client = AgentClient.from_identity(args.identity.expanduser())
            print(json.dumps(import_paper(client, args.url, args.filename, args.recipient, audience=args.audience)))
        elif args.command == "upload-artifact":
            client = AgentClient.from_identity(args.identity.expanduser())
            print(json.dumps(upload_artifact(client, args)))
        elif args.command == "heartbeat":
            client = AgentClient.from_identity(args.identity.expanduser())
            try:
                send_heartbeats(client, once=args.once)
            except KeyboardInterrupt:
                return
        elif args.command == "run-schedule":
            command = args.runner_command
            if command[:1] == ["--"]:
                command = command[1:]
            if not command:
                raise ValueError("Provide a local research command after --.")
            identity = args.identity.expanduser()
            try:
                run_schedule(AgentClient.from_identity(identity), identity, command, once=args.once)
            except KeyboardInterrupt:
                return
        elif args.command == "git-header":
            client = AgentClient.from_identity(args.identity.expanduser())
            if client.base != library_origin(args.server_url):
                raise ValueError("Use an identity enrolled with the destination library.")
            client.authorize()
            print(f"Authorization: Bearer {client.key}")
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
