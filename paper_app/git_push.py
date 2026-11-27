"""Validate writable Git refs before recording their accepted objects."""

import json
import re
import subprocess
from tempfile import TemporaryFile

from . import library, projects, sharing

MAX_PUSH_BYTES = 16 * 1024 * 1024
MAX_REPO_BYTES = 32 * 1024 * 1024
MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_COMMITS = 100
MAX_TREE_ENTRIES = 5000
OID = rb"[0-9a-f]{40}"
COMMAND = re.compile(rb"(" + OID + rb") (" + OID + rb") (refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,119})\0(.*)")


class PushRejected(ValueError):
    pass


def request_update(body, ref):
    try:
        length = int(body[:4], 16)
    except ValueError:
        raise PushRejected("Invalid Git push command.") from None
    match = COMMAND.fullmatch(body[4:length].rstrip(b"\n"))
    if (not match or body[length:length + 4] != b"0000"
            or (ref and match[3] != ref.encode()) or not projects.valid_branch(match[3].decode()[11:])):
        branch = ref.removeprefix("refs/heads/") if ref else "a project branch"
        raise PushRejected(f"Push one update to {branch} at a time.")
    old, new = match[1].decode(), match[2].decode()
    if new == "0" * 40:
        raise PushRejected("Deleting the branch is disabled.")
    return old, new, match[4].split(), match[3].decode()


def packet(value):
    return f"{len(value) + 4:04x}".encode() + value


def rejection(ref, capabilities, message):
    message = message.replace("\r", " ").replace("\n", " ")
    report = packet(b"unpack ok\n") + packet(f"ng {ref} {message}\n".encode()) + b"0000"
    return packet(b"\x01" + report) + b"0000" if b"side-band-64k" in capabilities else report


def tree(repo, commit):
    rows = repo.output("ls-tree", "-r", "-l", "-z", commit).split(b"\0")[:-1]
    if len(rows) > MAX_TREE_ENTRIES:
        raise PushRejected("This commit contains too many files.")
    entries = {}
    for row in rows:
        attributes, path = row.split(b"\t", 1)
        mode, kind, blob, size = attributes.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise PushRejected("Commit ordinary files. Symbolic links and submodules are disabled.")
        entries[path] = (blob.decode(), int(size))
    return entries


def updates(repo, old, new, kind, resource_id):
    lines = repo.output("rev-list", "--reverse", "--parents", f"--max-count={MAX_COMMITS + 1}", f"{old}..{new}").splitlines()
    if not lines or len(lines) > MAX_COMMITS:
        raise PushRejected(f"Push at most {MAX_COMMITS} commits at a time.")
    previous = old.encode()
    documents = []
    metadata_revision = read_document(repo, tree(repo, old), resource_id)[0] if kind == "documents" else None
    for line in lines:
        commit, *parents = line.split()
        if parents != [previous]:
            raise PushRejected("Use a linear fast-forward push. Rebase local commits on the remote branch.")
        previous = commit
        entries = tree(repo, commit.decode())
        if kind == "documents":
            recorded_revision, document = read_document(repo, entries, resource_id)
            if recorded_revision != metadata_revision:
                raise PushRejected("Keep the revision number in document.json unchanged.")
            documents.append(document)
        elif any(size > MAX_SOURCE_BYTES for _, size in entries.values()):
            raise PushRejected("Source files can be up to 5 MiB. Upload large files as experiment artifacts.")
    return documents


def read_document(repo, entries, resource_id):
    if set(entries) != {b"document.md", b"document.json"}:
        raise PushRejected("A document commit must contain document.md and document.json.")
    markdown, markdown_bytes = entries[b"document.md"]
    metadata, metadata_bytes = entries[b"document.json"]
    if markdown_bytes > 400_000 or metadata_bytes > 16_384:
        raise PushRejected("Document Markdown or metadata exceeds the size limit.")
    try:
        description = json.loads(repo.output("cat-file", "blob", metadata))
        body = repo.output("cat-file", "blob", markdown).decode("utf-8")
    except (UnicodeError, ValueError):
        raise PushRejected("Use UTF-8 Markdown and valid JSON metadata.") from None
    if (not isinstance(description, dict) or set(description) != {"document_id", "revision", "title", "source_url"}
            or type(description["document_id"]) is not int or description["document_id"] != resource_id
            or type(description["revision"]) is not int or description["revision"] < 1):
        raise PushRejected("Keep the document ID and metadata fields from the original checkout.")
    title, source = description["title"], description["source_url"]
    if (not isinstance(title, str) or not 1 <= len(title) <= 160 or title != title.strip()
            or "\0" in title or len(body) > 100_000 or "\0" in body):
        raise PushRejected("Use a title up to 160 characters and Markdown up to 100,000 characters.")
    if source != "":
        try:
            sharing.validate_news_source(source)
        except ValueError as error:
            raise PushRejected(str(error)) from None
    return description["revision"], {"title": title, "markdown": body, "source_url": source}


def project_updates(repo, old, new, refs):
    if old != "0" * 40:
        try:
            repo.run("merge-base", "--is-ancestor", old, new)
        except subprocess.CalledProcessError:
            raise PushRejected("Use a fast-forward update. Fetch and merge or rebase first.") from None
    lines = repo.output("rev-list", f"--max-count={MAX_COMMITS + 1}", new, "--not", *set(refs.values())).splitlines()
    if len(lines) > MAX_COMMITS:
        raise PushRejected(f"Push at most {MAX_COMMITS} new commits at a time.")
    for commit in lines:
        if any(size > MAX_SOURCE_BYTES for _, size in tree(repo, commit.decode()).values()):
            raise PushRejected("Source files can be up to 5 MiB. Upload large files as experiment artifacts.")


def pack_refs(repo, *refs):
    with TemporaryFile() as packed:
        repo.run("pack-objects", "--stdout", "--revs", input=("\n".join(refs) + "\n").encode(), stdout=packed)
        if packed.tell() > MAX_REPO_BYTES:
            raise PushRejected("This Git repository exceeds its 32 MiB packed limit.")
        packed.seek(0)
        return packed.read()


def persist(db, account, kind, resource_id, base_revision, state, new, packed, documents, storage_limit):
    row = db.execute(
        "SELECT head,base_revision,length(pack) AS bytes FROM git_repository_state WHERE kind=? AND resource_id=?",
        (kind, resource_id),
    ).fetchone()
    if (row["head"] if row else None) != state:
        raise PushRejected("The branch changed while you were pushing. Fetch and rebase first.")
    library.require_upload_space(db, storage_limit, max(0, len(packed) - (row["bytes"] if row else 0)))
    if kind == "documents":
        for revision, data in enumerate(documents, start=base_revision):
            sharing.save_document(db, account, {"document_id": resource_id, "revision": revision, **data},
                                  allow_empty_source=True)
        base_revision += len(documents)
    db.execute(
        "INSERT INTO git_repository_state(kind,resource_id,base_revision,head,pack) VALUES (?,?,?,?,?) "
        "ON CONFLICT(kind,resource_id) DO UPDATE SET base_revision=excluded.base_revision,head=excluded.head,pack=excluded.pack",
        (kind, resource_id, base_revision, new, packed),
    )
