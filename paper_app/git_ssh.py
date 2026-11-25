"""Authorize OpenSSH keys and serve only Paper Library Git commands."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import accounts, database, git_push, git_repos, library, sharing

REPOSITORY = re.compile(r"/?git/(documents|experiments)/([1-9][0-9]{0,18})\.git")
CONTEXT = "PAPER_GIT_SSH_CONTEXT"


def settings(config):
    if not config.is_absolute():
        raise ValueError("Use an absolute SSH workspace configuration path.")
    with config.open("rb") as stream:
        options = tomllib.load(stream)
    if options.keys() - {"database", "postgres_url", "pdf_dir", "storage_quota_mib"}:
        raise ValueError("Unknown SSH workspace configuration field.")
    if set(options) & {"postgres_url", "pdf_dir"}:
        url, pdf_dir = options.get("postgres_url"), options.get("pdf_dir")
        if ("database" in options or not isinstance(url, str) or not url.startswith(("postgresql://", "postgres://"))
                or not isinstance(pdf_dir, str) or not Path(pdf_dir).is_absolute()):
            raise ValueError("Set postgres_url and an absolute pdf_dir for PostgreSQL.")
        target = database.PostgreSQL(url, Path(pdf_dir))
    else:
        path = options.get("database")
        if not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_file():
            raise ValueError("Set database to the workspace's existing absolute SQLite path.")
        target = Path(path)
    limit = options.get("storage_quota_mib", 0)
    if type(limit) is not int or limit < 0:
        raise ValueError("Set storage_quota_mib to a nonnegative integer.")
    return target, limit * 1024**2


def account_for(db, key):
    rows = db.execute(f"""
        SELECT a.id,a.username,{accounts.ROLE_SQL.format(alias='a')} AS role
        FROM accounts a WHERE a.disabled_at IS NULL AND (
            (a.role='user' AND EXISTS (
                SELECT 1 FROM human_public_keys k WHERE k.account_id=a.id AND k.public_key=?))
            OR (a.role='ai' AND EXISTS (
                SELECT 1 FROM ai_public_keys k WHERE k.account_id=a.id AND k.public_key=?)))
        LIMIT 2
    """, (key, key)).fetchall()
    if len(rows) != 1:
        raise accounts.SignInRequired
    return dict(rows[0])


def authorized_key(config, key_type, key_blob):
    if key_type != "ssh-ed25519" or not re.fullmatch(r"[A-Za-z0-9+/]{68}", key_blob):
        return None
    try:
        candidate = serialization.load_ssh_public_key(f"{key_type} {key_blob}".encode())
    except (ValueError, TypeError):
        return None
    if not isinstance(candidate, Ed25519PublicKey):
        return None
    key = candidate.public_bytes_raw()
    target, _ = settings(config)
    try:
        with library.connect(target) as db:
            account_for(db, key)
    except accounts.SignInRequired:
        return None
    forced = shlex.join([
        sys.executable, "-I", "-m", "paper_app.git_ssh", "--config", str(config), "serve", key.hex(),
    ]).replace("\\", "\\\\").replace('"', '\\"')
    return f'restrict,command="{forced}" {key_type} {key_blob}'


def parse_command(original):
    fields = shlex.split(original)
    if len(fields) != 2 or fields[0] not in ("git-upload-pack", "git-receive-pack"):
        raise ValueError("Use Git clone, fetch, or push with a Paper Library repository URL.")
    match = REPOSITORY.fullmatch(fields[1])
    if not match or int(match[2]) >= 2**63:
        raise ValueError("Repository unavailable.")
    return fields[0].removeprefix("git-"), match[1], int(match[2])


def git_executable():
    executable = shutil.which("git", path=os.defpath)
    if not executable:
        raise ValueError("Git is unavailable on this server.")
    return executable


def install_hook(repo, directory, config, key, kind, resource, prepared):
    hook_dir = Path(directory) / "hooks"
    hook_dir.mkdir(mode=0o700)
    for name, action in (("pre-receive", "check"), ("reference-transaction", "accept")):
        hook = hook_dir / name
        command = shlex.join([sys.executable, "-m", "paper_app.git_ssh", "--config", str(config), action])
        hook.write_text('#!/bin/sh\nexec ' + command + ' "$@"\n', encoding="utf-8")
        hook.chmod(0o700)
    repo.run("config", "core.hooksPath", str(hook_dir))
    repo.env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    repo.env[CONTEXT] = json.dumps([directory, key.hex(), kind, resource, *prepared])


def serve(config, key):
    operation, kind, resource = parse_command(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    writing = operation == "receive-pack"
    target, _ = settings(config)
    with TemporaryDirectory(prefix="paper-ssh-") as directory:
        with library.connect(target) as db:
            database.begin(db)
            account = account_for(db, key)
            row = git_repos.resource_scope(db, account, kind, resource, writing=writing)
            repo = git_repos.Repository(git_executable(), directory, os.environ.get("GIT_PROTOCOL"))
            prepared = git_repos.prepare(repo, db, account, kind, resource, row, writing)
        if writing:
            install_hook(repo, directory, config, key, kind, resource, prepared)
        repo.run(operation, ".", stdin=sys.stdin.buffer, stdout=sys.stdout.buffer, stderr=sys.stderr.buffer)


def push_context():
    if not os.environ.get(CONTEXT):
        raise ValueError("Git push context is unavailable.")
    return json.loads(os.environ[CONTEXT])


def check_update(ref, *, allow_head=False):
    body = sys.stdin.buffer.read(512)
    command = rb"([0-9a-f]{40}) ([0-9a-f]{40}) "
    matches = [re.fullmatch(command + rb"(refs/heads/(?:main|source)|HEAD)", line) for line in body.splitlines()]
    updates = {match[3].decode(): (match[1].decode(), match[2].decode()) for match in matches if match}
    permitted = {ref, "HEAD"} if allow_head and ref == "refs/heads/main" else {ref}
    if (len(body) >= 512 or not body.endswith(b"\n") or len(updates) != len(matches)
            or ref not in updates or updates.keys() - permitted or any(pair != updates[ref] for pair in updates.values())):
        raise git_push.PushRejected(f"Push one update to {ref.removeprefix('refs/heads/')} at a time.")
    old, new = updates[ref]
    if new == "0" * 40:
        raise git_push.PushRejected("Deleting the branch is disabled.")
    return old, new


def accept(config):
    directory, key_hex, kind, resource, ref, revision, state = push_context()
    old, new = check_update(ref, allow_head=True)
    target, limit = settings(config)
    repo = git_repos.Repository(git_executable(), directory, None, initialize=False)
    if old != repo.head(ref):
        raise git_push.PushRejected("The branch changed. Fetch and rebase first.")
    key = bytes.fromhex(key_hex)
    git_repos.accept_update(repo, target, lambda db: account_for(db, key), kind, resource, revision,
                            state, old, new, limit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    commands = parser.add_subparsers(dest="action", required=True)
    lookup = commands.add_parser("authorized-key")
    lookup.add_argument("key_type")
    lookup.add_argument("key_blob")
    connection = commands.add_parser("serve")
    connection.add_argument("key_hex")
    commands.add_parser("check")
    transaction = commands.add_parser("accept")
    transaction.add_argument("phase", choices=("preparing", "prepared", "committed", "aborted"))
    args = parser.parse_args()
    try:
        if args.action == "authorized-key":
            line = authorized_key(args.config, args.key_type, args.key_blob)
            if line:
                print(line)
        elif args.action == "serve":
            if not re.fullmatch(r"[0-9a-f]{64}", args.key_hex):
                raise accounts.SignInRequired
            serve(args.config, bytes.fromhex(args.key_hex))
        elif args.action == "check":
            check_update(push_context()[4])
        elif args.phase == "prepared":
            accept(args.config)
    except (accounts.SignInRequired, sharing.AccessDenied):
        parser.exit(1, "Paper Library Git access is unavailable.\n")
    except (ValueError, sharing.EditConflict) as error:
        parser.exit(1, f"Paper Library Git: {error}\n")
    except database.ERRORS + (OSError, subprocess.SubprocessError):
        parser.exit(1, "Paper Library could not process this Git request.\n")


if __name__ == "__main__":
    main()
