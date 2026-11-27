import base64
import os
import shutil
import subprocess
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from paper_app import accounts, experiments, git_push, git_repos, library, projects
from paper_app.server import Handler
from test_skill_api import request


def push_initial_project_commit(database, project_id, account):
    with tempfile.TemporaryDirectory() as directory:
        repo = git_repos.Repository(shutil.which("git"), directory, None)
        ref = "refs/heads/main"
        repo.import_history(ref, [("Agent", "2026-01-01 00:00:00", "Initial work", {"baseline.txt": b"Baseline"})])
        head = repo.head(ref)
        git_repos.accept_update(repo, database, lambda db: account, "projects", project_id, 1,
                               None, "0" * 40, head, 0, ref=ref)
        return head


@unittest.skipUnless(shutil.which("git"), "Git is required")
class ProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "library.sqlite3"
        library.initialize(self.database)
        self.keys = {}
        with library.connect(self.database) as db:
            for name, role in (("owner", "user"), ("agent", "local"), ("reader", "member")):
                account_id = accounts.create_account(db, name, "example password", role)
                self.keys[name] = accounts.create_key(db, account_id, "Test")
                if name == "agent":
                    self.experiment = experiments.save_experiment(db, {"id": account_id, "role": role},
                                                                  {"title": "Simulation"})
        self.project = self.api("/api/projects", {"action": "create", "title": "Research"})["project"]
        self.project_route = f"/api/projects?id={self.project['id']}"

    def api(self, path, data=None, *, user="owner", expected=200, key=None):
        status, result = request(self.database, path, data=data, key=key or self.keys[user])
        self.assertEqual(status, expected, result)
        return result

    def share(self, username, access):
        return self.api("/api/projects", {"action": "share", "id": self.project["id"],
                                          "username": username, "access": access})

    def token(self, access, *, user="owner"):
        return self.api("/api/git-tokens", {"action": "create", "kind": "projects",
                                           "resource_id": self.project["id"], "access": access, "days": 1},
                        user=user)

    def test_project_sharing_experiment_and_physical_proposals(self):
        self.api(self.project_route, user="agent", expected=404)
        self.share("agent", "write")
        self.share("reader", "read")
        link = {"action": "link_experiment", "id": self.project["id"], "experiment_id": self.experiment}
        self.api("/api/projects", link, expected=403)
        self.api("/api/projects", link, user="agent", expected=409)
        push_initial_project_commit(self.database, self.project["id"], {"id": 1, "role": "user"})
        linked = self.api("/api/projects", link, user="agent")["project"]
        branch = f"experiment/{self.experiment}"
        self.assertEqual(linked["branches"][branch], linked["branches"]["main"])
        detail = self.api(f"/api/experiment-detail?id={self.experiment}", user="agent")["experiment"]
        self.assertEqual(detail["project"]["branch"], branch)
        fields = {field: field.replace("_", " ") for field in projects.PLAN_FIELDS}
        path = "/api/physical-proposals"
        proposal = {"project_id": self.project["id"], "title": "Calibrate sensors", **fields}
        self.api(path, proposal, user="reader", expected=403)
        saved = self.api(path, proposal, user="agent")["proposals"][0]
        self.assertEqual(saved["status"], "proposed")
        self.assertFalse(self.api(path, user="reader")["proposals"][0]["editable"])
        edit = {**proposal, "id": saved["id"], "revision": saved["revision"], "measurement": "Record baseline"}
        self.assertEqual(self.api(path, edit)["proposals"][0]["measurement"], "Record baseline")
        self.api(path, edit, expected=409)
        self.share("reader", "none")
        self.assertEqual(self.api(path, user="reader")["proposals"], [])

    def test_browser_reads_tree_and_history_with_project_access(self):
        project_id = self.project["id"]
        route = f"/api/project-browser?id={project_id}"
        self.api(route, user="reader", expected=404)
        self.share("reader", "read")
        self.assertEqual(self.api(route, user="reader")["kind"], "empty")
        initial = push_initial_project_commit(self.database, project_id, {"id": 1, "role": "user"})
        with tempfile.TemporaryDirectory() as directory, library.connect(self.database) as db:
            repo = git_repos.Repository(shutil.which("git"), directory, None)
            owner = {"id": 1, "role": "user"}
            project = projects.scope(db, owner, project_id)
            git_repos.prepare(repo, db, owner, "projects", project_id, project, False)
            ref = "refs/heads/main"
            records = [("Agent", "2026-01-01 00:00:00", f"Update {number}",
                        {"docs/notes.txt": b"Finding", "docs/image.bin": b"\x00\x01"})
                       for number in range(26)]
            repo.import_history(ref, records, initial)
            head = repo.head(ref)
            db.execute("UPDATE projects SET refs=?,pack=? WHERE id=?",
                       (f'{{"main":"{head}","baseline":"{initial}"}}', git_push.pack_refs(repo, head), project_id))

        root = self.api(route, user="reader")
        self.assertEqual(root["entries"], [{"kind": "directory", "name": "docs"}])
        self.assertEqual((len(root["history"]), root["history"][0]["subject"]), (25, "Update 25"))
        older = self.api(f"{route}&offset={root['next_offset']}", user="reader")
        self.assertEqual(len(older["history"]), 2)
        self.assertEqual(older["history"][-1]["id"], initial)
        self.assertEqual(older["previous_offset"], 0)
        preview = self.api(f"{route}&path=docs/notes.txt", user="reader")
        self.assertEqual((preview["preview"], preview["text"]), ("text", "Finding"))
        self.assertEqual(self.api(f"{route}&path=docs/image.bin")["preview"], "binary")
        self.assertEqual(self.api(f"{route}&commit={initial}")["entries"], [{"kind": "file", "name": "baseline.txt"}])
        self.api(f"{route}&branch=baseline&commit={head}", expected=404)
        self.api(f"{route}&path=docs/../README.md", expected=400)
        self.api(f"{route}&path=missing", expected=404)

    def test_only_owner_can_delete_project_and_related_records_survive(self):
        project_id = self.project["id"]
        push_initial_project_commit(self.database, project_id, {"id": 1, "role": "user"})
        self.share("agent", "write")
        self.share("reader", "read")
        self.token("read", user="reader")
        self.token("write", user="agent")
        project = self.api("/api/projects", {"action": "link_experiment", "id": project_id,
                                            "experiment_id": self.experiment}, user="agent")["project"]
        fields = {field: field.replace("_", " ") for field in projects.PLAN_FIELDS}
        self.api("/api/physical-proposals", {"project_id": project_id, "title": "Field test", **fields},
                 user="agent")
        deletion = {"action": "delete", "id": project_id, "revision": project["revision"],
                    "git_revision": project["git_revision"]}
        self.api("/api/projects", deletion, user="agent", expected=403)
        self.api("/api/projects", {**deletion, "git_revision": project["git_revision"] - 1}, expected=409)
        self.assertEqual(self.api("/api/projects", deletion)["deleted_project_id"], project_id)
        self.api(self.project_route, expected=404)
        self.api(f"/api/project-browser?id={project_id}", expected=404)
        self.api(f"/git/projects/{project_id}.git/info/refs?service=git-upload-pack", expected=404)
        self.assertEqual(self.api("/api/projects")["projects"], [])
        self.assertEqual(self.api("/api/git-tokens", user="reader")["tokens"], [])
        self.assertEqual(self.api("/api/git-tokens", user="agent")["tokens"], [])
        self.assertEqual(self.api("/api/physical-proposals", user="reader")["proposals"], [])
        self.assertIsNone(self.api("/api/physical-proposals", user="agent")["proposals"][0]["project_id"])
        experiment = self.api(f"/api/experiment-detail?id={self.experiment}", user="agent")["experiment"]
        self.assertNotIn("project", experiment)
        new_project = self.api("/api/projects", {"action": "create", "title": "New"})["project"]
        self.assertGreater(new_project["id"], project_id)

    def test_git_tokens_scope_revoke_and_expire(self):
        self.share("reader", "read")
        self.api("/api/git-tokens", {"action": "create", "kind": "projects",
                                    "resource_id": self.project["id"], "access": "write", "days": 1},
                 user="reader", expected=403)
        token_response = self.token("read", user="reader")
        token, token_id = token_response["token"], token_response["tokens"][0]["id"]
        self.api("/api/projects", key=token, expected=401)
        self.assertNotIn("token", self.api("/api/git-tokens", user="reader"))
        self.assertEqual(self.api("/api/git-tokens")["tokens"], [])
        with patch("paper_app.git_tokens.time.time", return_value=token_response["tokens"][0]["expires"]):
            self.assertEqual(self.api("/api/git-tokens", user="reader")["tokens"], [])
        self.api("/api/git-tokens", {"action": "revoke", "id": token_id}, user="reader")
        self.assertEqual(self.api("/api/git-tokens", user="reader")["tokens"], [])

    def test_clone_push_and_pull_with_scoped_tokens(self):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except PermissionError:
            self.skipTest("Loopback sockets are unavailable")
        with server:
            server.database, server.public_url, server.google_config = self.database, None, None
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                self.share("agent", "write")
                self.share("reader", "read")
                write_token = self.token("write", user="agent")["token"]
                reader_token = self.token("read", user="reader")
                read_token = reader_token["token"]
                basic = base64.b64encode(f"reader:{read_token}".encode()).decode()
                origin = f"http://127.0.0.1:{server.server_port}"
                url = origin + self.project["git_path"]

                def git(path, token, *args, expected=True):
                    args = ["git", "-C", str(path), "--config-env=http.extraHeader=PAPER_GIT_AUTH", *args]
                    header = f"Basic {basic}" if token == read_token else f"Bearer {token}"
                    env = {**os.environ, "PAPER_GIT_AUTH": f"Authorization: {header}", "GIT_TERMINAL_PROMPT": "0"}
                    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode == 0, expected, result.stderr)
                    return result.stdout.strip()

                self.assertEqual(git(self.root, write_token, "ls-remote", url), "")
                git(self.root, read_token, "clone", url, "reader")
                git(self.root, write_token, "init", "--initial-branch=main", "agent")
                writer, reader = self.root / "agent", self.root / "reader"
                git(writer, write_token, "remote", "add", "origin", url)
                (writer / "results.txt").write_text("observations", encoding="utf-8")
                git(writer, write_token, "add", "results.txt")
                git(writer, write_token, "-c", "user.name=Agent", "-c", "user.email=agent@example.test",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Save observations")
                git(writer, write_token, "push", "origin", "main")
                self.assertEqual(self.api(f"/api/project-browser?id={self.project['id']}")["history"][0]["subject"],
                                 "Save observations")
                git(writer, write_token, "switch", "-c", "analysis/results")
                git(writer, write_token, "push", "origin", "analysis/results")
                git(writer, read_token, "push", "origin", "analysis/results:main", expected=False)
                git(reader, read_token, "fetch", "origin")
                git(reader, read_token, "switch", "--track", "origin/analysis/results")
                git(reader, read_token, "pull", "--ff-only")
                self.assertEqual((reader / "results.txt").read_text(), "observations")
                git(reader, read_token, "ls-remote", f"{origin}/git/experiments/{self.experiment}.git", expected=False)
                self.api("/api/git-tokens", {"action": "revoke", "id": reader_token["tokens"][0]["id"]}, user="reader")
                git(reader, read_token, "fetch", "origin", expected=False)
            finally:
                server.shutdown()
                thread.join(timeout=5)
