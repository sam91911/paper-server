"""Fetch and verify artifact pointers in a Paper Library experiment checkout."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request

from .agent import AgentClient
from .review import LibraryClient, library_origin

POINTER_SUFFIX = ".paper-pointer.json"


def git(checkout, *args):
    return subprocess.check_output(["git", "-C", str(checkout), *args], stderr=subprocess.DEVNULL, timeout=10)


def matches(path, size, digest):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == digest


def fetch(checkout, pointer, client):
    name = re.fullmatch(r"artifacts/([1-9][0-9]*)/([1-9][0-9]*)\.paper-pointer\.json", pointer)
    source = checkout / pointer
    if not name or source.resolve() != source or source.stat().st_size > 8192:
        raise ValueError(f"Invalid pointer path {pointer}.")
    metadata = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("format") != "paper-library-artifact-v1":
        raise ValueError(f"Unsupported pointer {pointer}.")
    item, version = name.groups()
    download = f"/research-versions/{version}/file"
    prefix = f"artifacts/{item}/{version}/"
    path, digest, size = (metadata.get(field) for field in ("path", "sha256", "size"))
    filename = path.removeprefix(prefix) if isinstance(path, str) and path.startswith(prefix) else ""
    if (metadata.get("download") != download or filename in ("", ".", "..")
            or re.search(r"[/\\:\x00-\x1f]", filename) or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest) or type(size) is not int or size < 0):
        raise ValueError(f"Invalid artifact metadata in {pointer}.")
    destination = checkout / prefix / filename
    if destination.resolve() != destination:
        raise ValueError(f"Refusing a symbolic link for {path}.")
    if destination.exists():
        if not matches(destination, size, digest):
            raise ValueError(f"Move the conflicting local file before refetching {path}.")
        return "Verified", path

    if isinstance(client, AgentClient):
        client.authorize()
    request = Request(client.base + download, headers={"Authorization": f"Bearer {client.key}"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temp:
        staged = Path(temp.name)
        try:
            total = 0
            sha256 = hashlib.sha256()
            with client.opener.open(request, timeout=30) as response:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > size:
                        raise ValueError(f"{path} exceeded the recorded size.")
                    sha256.update(chunk)
                    temp.write(chunk)
            if total != size or sha256.hexdigest() != digest:
                raise ValueError(f"{path} did not match the recorded size and SHA-256.")
            temp.close()
            os.link(staged, destination)
        finally:
            staged.unlink(missing_ok=True)
    return "Fetched", path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--identity", type=Path, help="Use an enrolled AI identity instead of PAPER_LIBRARY_KEY.")
    parser.add_argument("--server-url", help="Confirm the library HTTPS origin when using an application key.")
    args = parser.parse_args()
    try:
        root = Path(os.fsdecode(git(args.checkout, "rev-parse", "--show-toplevel").rstrip(b"\n"))).resolve()
        remote = urlsplit(git(root, "remote", "get-url", "origin").decode().strip())
        if (not re.fullmatch(r"/git/experiments/[1-9][0-9]*\.git", remote.path)
                or remote.query or remote.fragment):
            raise ValueError("Use a checkout cloned from a Paper Library experiment URL.")
        origin = None if remote.scheme == "ssh" else library_origin(f"{remote.scheme}://{remote.netloc}")
        if args.identity:
            client = AgentClient.from_identity(args.identity)
            if (origin and client.base != origin
                    or args.server_url and client.base != library_origin(args.server_url)):
                raise ValueError("Use an identity enrolled with this checkout's server.")
        else:
            key = os.getenv("PAPER_LIBRARY_KEY")
            if not key:
                raise ValueError("Set PAPER_LIBRARY_KEY to your application key.")
            if not args.server_url or (origin and library_origin(args.server_url) != origin):
                raise ValueError("Pass the checkout's trusted library origin with --server-url.")
            client = LibraryClient(None, key, server_url=args.server_url)
        for item in git(root, "ls-files", "-z", "--", "*" + POINTER_SUFFIX).split(b"\0"):
            if item:
                action, path = fetch(root, os.fsdecode(item), client)
                print(f"{action} {path}")
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Paper Library artifacts: {error}\n")


if __name__ == "__main__":
    main()
