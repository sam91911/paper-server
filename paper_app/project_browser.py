"""Read repository trees and reachable commit history for project collaborators."""

import json
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from . import git_repos, projects

PAGE_SIZE = 25
PREVIEW_BYTES = 128 * 1024


def read(db, account, project_id, *, branch, path="", commit=None, offset=0):
    project = projects.scope(db, account, project_id)
    refs = json.loads(project["refs"])
    if not refs and not path and commit is None:
        return {"kind": "empty", "entries": [], "history": [], "path": "", "branch": branch,
                "head": None, "commit": None, "previous_offset": None, "next_offset": None}
    branch = branch or projects.default_branch(refs)
    if branch not in refs:
        raise LookupError("Branch unavailable.")
    if len(path.encode("utf-8")) > 4096 or "\x00" in path or (path and any(
            segment in ("", ".", "..") for segment in path.split("/"))):
        raise ValueError("Choose a repository path.")
    if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Choose a commit from the branch history.")
    head = refs[branch]
    revision = commit or head
    executable = shutil.which("git")
    if not executable:
        raise RuntimeError("Git is unavailable on this server.")
    pack = db.execute("SELECT pack FROM projects WHERE id=?", (project_id,)).fetchone()[0]
    with TemporaryDirectory(prefix="paper-project-view-") as directory:
        repo = git_repos.Repository(executable, directory, None)
        repo.run("index-pack", "--stdin", input=bytes(pack))
        if revision != head:
            try:
                repo.run("merge-base", "--is-ancestor", revision, head)
            except subprocess.CalledProcessError:
                raise LookupError("Commit unavailable on this branch.") from None
        contents = read_path(repo, revision, path)
        history = repo.output("log", "-z", "--format=%H%x00%an%x00%aI%x00%s",
                              f"--skip={offset}", f"--max-count={PAGE_SIZE + 1}", head, "--")
        fields = history.decode("utf-8", "replace").split("\x00")[:-1]
        commits = []
        for index in range(0, len(fields), 4):
            oid, author, date, subject = fields[index:index + 4]
            commits.append({"id": oid, "author": author, "date": date, "subject": subject})
        return {"branch": branch, "head": head, "commit": revision, "path": path, **contents,
                "history": commits[:PAGE_SIZE], "previous_offset": max(0, offset - PAGE_SIZE) if offset else None,
                "next_offset": offset + PAGE_SIZE if len(commits) > PAGE_SIZE else None}


def read_path(repo, revision, path):
    object_name = f"{revision}:{path}" if path else f"{revision}^{{tree}}"
    try:
        kind = repo.output("cat-file", "-t", object_name).strip()
    except subprocess.CalledProcessError:
        raise LookupError("Path unavailable at this commit.") from None
    if kind == b"tree":
        entries = []
        for record in repo.output("ls-tree", "-z", object_name).split(b"\x00")[:-1]:
            metadata, name = record.split(b"\t", 1)
            mode, entry_kind, _ = metadata.split()
            try:
                label = name.decode("utf-8")
            except UnicodeDecodeError:
                label = name.decode("utf-8", "replace")
                entry_kind = b"other"
            if mode == b"120000":
                entry_kind = b"other"
            entries.append({"name": label, "kind": {b"tree": "directory", b"blob": "file"}.get(entry_kind, "other")})
        entries.sort(key=lambda entry: (entry["kind"] != "directory", entry["name"].casefold(), entry["name"]))
        return {"kind": "directory", "entries": entries}
    if kind != b"blob":
        raise LookupError("Path unavailable at this commit.")
    size = int(repo.output("cat-file", "-s", object_name))
    result = {"kind": "file", "size": size, "text": None}
    if size > PREVIEW_BYTES:
        return {**result, "preview": "too_large"}
    raw = repo.output("cat-file", "blob", object_name)
    if b"\x00" not in raw:
        try:
            return {**result, "text": raw.decode("utf-8"), "preview": "text"}
        except UnicodeDecodeError:
            pass
    return {**result, "preview": "binary"}
