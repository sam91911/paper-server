"""Serve Git histories for documents and experiment source, with scoped artifact views."""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile

from . import accounts, database, experiments, git_push, library, sharing

ROUTE = re.compile(r"/git/(documents|experiments)/([1-9][0-9]{0,18})\.git/(info/refs|git-upload-pack|git-receive-pack)")
REQUEST_MAX = 1024 * 1024
GIT_TIMEOUT = 60


def write_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def document_commits(db, resource_id, first_revision):
    revisions = db.execute(
        "SELECT * FROM document_versions WHERE document_id=? AND revision>=? ORDER BY revision",
        (resource_id, first_revision),
    )
    for revision in revisions:
        metadata = {key: revision[key] for key in ("document_id", "revision", "title", "source_url")}
        yield (revision["author"], revision["saved"], f"Document revision {revision['revision']}", {
            "document.md": revision["markdown"].encode(),
            "document.json": write_json(metadata),
        })


def experiment_commit(db, account, resource_id):
    detail = experiments.detail(db, account, resource_id)
    experiment = detail["experiment"]
    metadata = {key: experiment[key] for key in ("id", "title", "description", "updated", "revision")}
    metadata["runs"] = [{key: run[key] for key in (
        "id", "title", "description", "status", "methods", "settings", "reproduction", "revision",
    )} for run in detail["runs"]]
    files = {".gitignore": b"/artifacts/*/*/\n"}
    items = []
    for item in detail["items"]:
        record = {key: item[key] for key in ("id", "run_id", "title", "kind")}
        record["versions"] = []
        for version in item["versions"]:
            descriptor = {key: version[key] for key in ("id", "number", "description")}
            if version["sha256"]:
                pointer = f"artifacts/{item['id']}/{version['id']}.paper-pointer.json"
                filename = version["filename"].replace(":", "_")
                files[pointer] = write_json({
                    "format": "paper-library-artifact-v1",
                    "path": f"artifacts/{item['id']}/{version['id']}/{filename}",
                    "download": f"/research-versions/{version['id']}/file",
                    "sha256": version["sha256"],
                    "size": version["size"],
                })
                descriptor["pointer"] = pointer
            elif version["external_ref"]:
                descriptor["external_ref"] = version["external_ref"]
            record["versions"].append(descriptor)
        items.append(record)
    metadata["artifacts"] = items
    files["experiment.json"] = write_json(metadata)
    files["README.md"] = (
        b"# Experiment checkout\n\nSee experiment.json for run commands and artifact versions.\n"
        b"Fetch and verify artifacts with python3 -m paper_client.artifacts --help.\n"
    )
    yield ("Paper Library", experiment["updated"], "Export experiment", files)


def write_history(stream, commits, ref, parent):
    previous = parent
    for index, (author, saved, message, files) in enumerate(commits, 1):
        timestamp = int(datetime.fromisoformat(saved).replace(tzinfo=timezone.utc).timestamp())
        body = (message + "\n").encode()
        stream.write(f"commit {ref}\nmark :{index}\n"
                     f"committer {author} <history@paper-library.invalid> {timestamp} +0000\n"
                     f"data {len(body)}\n".encode())
        stream.write(body + b"\n")
        if previous is not None:
            stream.write(f"from {previous}\n".encode())
        stream.write(b"deleteall\n")
        for name, content in sorted(files.items()):
            stream.write(f"M 100644 inline {name}\ndata {len(content)}\n".encode())
            stream.write(content + b"\n")
        stream.write(b"\n")
        previous = f":{index}"
    if previous is None:
        raise LookupError
    stream.write(b"done\n")
    stream.seek(0)


def git_environment(home, protocol=None):
    env = {"PATH": os.defpath, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    if protocol == "version=2":
        env["GIT_PROTOCOL"] = protocol
    return env


class Repository:
    def __init__(self, executable, directory, protocol, *, initialize=True):
        self.path = Path(directory) / "repo.git"
        self.command = [executable, "-C", str(self.path)]
        self.env = git_environment(directory, protocol)
        if initialize:
            subprocess.run([executable, "init", "--quiet", "--bare", "--template=", "--initial-branch=main", str(self.path)],
                           env=self.env, check=True, timeout=GIT_TIMEOUT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run(self, *args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs):
        return subprocess.run([*self.command, *args], env=self.env, stdout=stdout,
                              stderr=stderr, check=True, timeout=GIT_TIMEOUT, **kwargs)

    def output(self, *args):
        return self.run(*args, stdout=subprocess.PIPE).stdout

    def head(self, ref):
        return self.output("rev-parse", "--verify", ref).decode().strip()

    def load(self, ref, state):
        self.run("index-pack", "--stdin", input=bytes(state["pack"]))
        self.run("update-ref", ref, state["head"])

    def import_history(self, ref, commits, parent=None):
        with TemporaryFile() as history:
            write_history(history, commits, ref, parent)
            self.run("fast-import", "--quiet", stdin=history)


def resource_scope(db, account, kind, resource, *, writing=False):
    if kind == "experiments":
        return experiments.require_experiment(db, resource, account, edit=writing)
    document = sharing.document_for(db, account, resource)
    if not document or document["kind"] != "document":
        raise sharing.AccessDenied
    if writing and not sharing.is_owner(db, account, document["owner_id"]):
        raise sharing.AccessDenied
    return document


def prepare(repo, db, account, kind, resource, row, writing):
    owner = kind == "documents" and sharing.is_owner(db, account, row["owner_id"])
    state = None
    if kind == "experiments" or owner:
        state = db.execute("SELECT * FROM git_repository_state WHERE kind=? AND resource_id=?",
                           (kind, resource)).fetchone()
    ref = "refs/heads/source" if kind == "experiments" else "refs/heads/main"
    if state:
        repo.load(ref, state)
    if kind == "experiments":
        if state is None:
            repo.import_history(ref, [("Paper Library", row["created"], "Start experiment source", {
                "README.md": b"# Experiment source\n\nMaintain source on this branch. Run metadata and artifact pointers are on main.\n",
            })])
        if not writing:
            repo.import_history("refs/heads/main", experiment_commit(db, account, resource))
    elif state is None or state["base_revision"] < row["revision"]:
        first = (state["base_revision"] + 1 if state else 1) if owner else row["revision"]
        repo.import_history(ref, document_commits(db, resource, first), state["head"] if state else None)
    if writing:
        for option, value in (
            ("receive.denyNonFastForwards", "true"), ("receive.denyDeletes", "true"),
            ("receive.fsckObjects", "true"), ("receive.maxInputSize", str(git_push.MAX_PUSH_BYTES)),
        ):
            repo.run("config", option, value)
    return ref, row["revision"], state["head"] if state else None


def read_packet_body(handler, maximum):
    handler.connection.settimeout(GIT_TIMEOUT)
    encoding = handler.headers.get("Transfer-Encoding")
    if encoding is None:
        size = int(handler.headers.get("Content-Length", "0"))
        if not 0 < size <= maximum:
            raise ValueError("Git request exceeds its size limit.")
        data = handler.rfile.read(size)
        if len(data) != size:
            raise ValueError("Incomplete Git request.")
        return data
    if encoding.lower() != "chunked" or handler.headers.get("Content-Length") is not None:
        raise ValueError("Invalid Git request encoding.")
    buffer = bytearray()
    while True:
        line = handler.rfile.readline(80)
        if not re.fullmatch(rb"[0-9a-fA-F]+\r\n", line):
            raise ValueError("Invalid Git request chunk.")
        size = int(line.strip(), 16)
        if size > maximum - len(buffer):
            raise ValueError("Git request exceeds its size limit.")
        if size == 0:
            if handler.rfile.readline(80) != b"\r\n" or not buffer:
                raise ValueError("Invalid end of Git request.")
            return bytes(buffer)
        segment = handler.rfile.read(size)
        if len(segment) != size or handler.rfile.read(2) != b"\r\n":
            raise ValueError("Incomplete Git request chunk.")
        buffer.extend(segment)


def accept_update(repo, target, authenticate, kind, resource, revision, state, old, new, storage_limit):
    documents = git_push.updates(repo, old, new, kind, resource)
    packed = git_push.pack_branch(repo, new)
    with library.connect(target) as db:
        database.begin(db, write=True)
        account = authenticate(db)
        row = resource_scope(db, account, kind, resource, writing=True)
        if kind == "documents" and revision != row["revision"]:
            raise git_push.PushRejected("The document changed in the browser. Fetch and rebase first.")
        git_push.persist(db, account, kind, resource, revision, state, new, packed, documents, storage_limit)


def receive(handler, repo, kind, resource, ref, revision, state, output):
    payload = read_packet_body(handler, git_push.MAX_PUSH_BYTES)
    if payload == b"0000":
        # Git probes authentication before a streamed push.
        repo.run("receive-pack", "--stateless-rpc", ".", input=payload, stdout=output)
        return
    old, new, capabilities = git_push.request_update(payload, ref)
    try:
        if old != repo.head(ref):
            raise git_push.PushRejected("The branch changed. Fetch and rebase first.")
        repo.run("receive-pack", "--stateless-rpc", ".", input=payload, stdout=output)
        if repo.head(ref) != new:
            # Git generated a native rejection without changing the temporary ref.
            return
        accept_update(repo, handler.server.database, handler.require_account, kind, resource, revision,
                      state, old, new, getattr(handler.server, "storage_limit", 0))
    except (git_push.PushRejected, sharing.EditConflict, library.UploadQuotaExceeded) as error:
        output.seek(0)
        output.truncate()
        output.write(git_push.rejection(ref, capabilities, str(error)))


def send_result(handler, output, media):
    length = output.tell()
    output.seek(0)
    handler.send_response(200)
    handler.send_header("Content-Type", media)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    try:
        shutil.copyfileobj(output, handler.wfile)
    except (BrokenPipeError, ConnectionResetError):
        pass


def serve(handler, url, match):
    kind, resource, action = match.groups()
    resource = int(resource)
    if resource >= 2**63:
        handler.send_json(404, {"error": "Repository unavailable."})
        return
    listing = handler.command == "GET" and action == "info/refs"
    service = url.query.removeprefix("service=") if listing and url.query.startswith("service=") else action
    media = f"application/x-{service}"
    transferring = (handler.command == "POST" and action == service and not url.query
                    and handler.headers.get_content_type() == media + "-request")
    if service not in ("git-upload-pack", "git-receive-pack") or not (listing or transferring):
        handler.send_json(404, {"error": "Repository unavailable."})
        return
    writing = service == "git-receive-pack"
    executable = shutil.which("git")
    if not executable:
        handler.send_json(503, {"error": "Git is unavailable on this server."})
        return
    try:
        with TemporaryDirectory(prefix="paper-git-") as directory, TemporaryFile() as output:
            protocol = None if writing else handler.headers.get("Git-Protocol")
            with library.connect(handler.server.database) as db:
                database.begin(db)
                account = handler.require_account(db)
                row = resource_scope(db, account, kind, resource, writing=writing)
                repo = Repository(executable, directory, protocol)
                ref, revision, state = prepare(repo, db, account, kind, resource, row, writing)
            pack = service.removeprefix("git-")
            if listing:
                output.write(git_push.packet(f"# service={service}\n".encode()) + b"0000")
                output.flush()
                repo.run(pack, "--stateless-rpc", "--advertise-refs", ".", stdin=subprocess.DEVNULL, stdout=output)
            elif writing:
                receive(handler, repo, kind, resource, ref, revision, state, output)
            else:
                repo.run(pack, "--stateless-rpc", ".", input=read_packet_body(handler, REQUEST_MAX), stdout=output)
            send_result(handler, output, media + ("-advertisement" if listing else "-result"))
    except accounts.SignInRequired:
        handler.send_json(401, {"error": "Use a Paper Library application key or an enrolled agent session for Git."})
    except sharing.AccessDenied:
        handler.send_json(403 if writing else 404, {"error": "Git access is unavailable."})
    except LookupError:
        handler.send_json(404, {"error": "Repository unavailable."})
    except ValueError as error:
        handler.send_json(400, {"error": str(error) or "Invalid Git request."})
    except (database.ERRORS + (OSError, subprocess.SubprocessError)):
        handler.send_json(503, {"error": "Could not process the Git request."})
