import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from paper_app import accounts, experiments, library, sharing
from paper_app.server import Handler
from paper_client import agent
from test_skill_api import request


class GitAndDiscussionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / "test.sqlite3"
        library.initialize(self.database)
        with library.connect(self.database) as db:
            self.author = {"id": accounts.create_account(db, "author", "test only password", "user"), "role": "user"}
            self.reader = {"id": accounts.create_account(db, "reader", "test only password", "user"), "role": "user"}
            self.keys = [accounts.create_key(db, actor["id"], "Test") for actor in (self.author, self.reader)]

    def api(self, path, data=None, *, reader=False, expected=200):
        code, response = request(self.database, path, key=self.keys[int(reader)], data=data)
        self.assertEqual(code, expected, response)
        return response

    def git(self, checkout, *args, key=None, header=None, success=True):
        env = os.environ.copy()
        command = ["git", "-C", str(checkout)]
        if key or header:
            env["PAPER_GIT_AUTH"] = header or f"Authorization: Bearer {key}"
            command.append("--config-env=http.extraHeader=PAPER_GIT_AUTH")
        result = subprocess.run([*command, *args], env=env, capture_output=True, timeout=35)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        return result

    def commit(self, checkout, message):
        self.git(checkout, "add", ".")
        self.git(checkout, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-m", message)
        return self.git(checkout, "rev-parse", "HEAD").stdout.strip()

    def test_discussion_uses_separate_listing_and_scoped_votes(self):
        regular = self.api("/api/documents", {"title": "Note", "markdown": "Ordinary"})["document_id"]
        thread = self.api("/api/discussions", {
            "title": "Discuss", "markdown": "First post", "audience": "users", "scheduled_at": 1893456000,
        })["document_id"]
        self.assertEqual([x["id"] for x in self.api("/api/documents")["documents"]], [regular])
        self.assertEqual([x["id"] for x in self.api("/api/discussions", reader=True)["documents"]], [thread])
        target = {"document_id": thread}
        self.assertEqual(self.api("/api/thread-votes", dict(target, vote=1), reader=True)["vote_score"], 1)
        self.assertEqual(self.api("/api/discussions", reader=True)["documents"][0]["my_vote"], 1)
        self.assertEqual(self.api("/api/thread-votes", dict(target, vote=-1), reader=True)["vote_score"], -1)
        self.assertEqual(self.api("/api/thread-votes", dict(target, vote=0), reader=True)["vote_score"], 0)
        self.api("/api/comments", dict(target, body="Research anchor", doi_refs=["10.1010/test"]), expected=400)
        comment = self.api("/api/comments", dict(target, body="Root", audience="users", scheduled_at=1900000000))["comment_id"]
        self.assertEqual(self.api("/api/documents", reader=True)["comments"], [])
        self.api("/api/comments", dict(target, body="Bad reply", parent_id=comment, scheduled_at=1900000000),
                 reader=True, expected=400)
        self.api("/api/comments", dict(target, body="Reply", parent_id=comment, audience="owner"))
        self.api("/api/thread-votes", dict(target, comment_id=comment, vote=1), reader=True)
        visible = self.api(f"/api/document-comments?document_id={thread}", reader=True)["comments"]
        self.assertEqual([(r["scheduled_at"], r["vote_score"], r["my_vote"]) for r in visible], [(1900000000, 1, 1)])
        self.api("/api/comments", dict(target, body="Private", comment_id=comment, audience="owner", scheduled_at=None))
        self.api("/api/thread-votes", dict(target, comment_id=comment, vote=-1), reader=True, expected=403)
        self.assertEqual(self.api(f"/api/document-comments?document_id={thread}", reader=True)["comments"], [])

    @unittest.skipUnless(shutil.which("git"), "Git is required")
    def test_git_history_and_experiment_pointers(self):
        with library.connect(self.database) as db:
            document = sharing.save_document(db, self.author, {"title": "Notes", "markdown": "private draft"})
            sharing.save_document(db, self.author, {
                "document_id": document, "title": "Notes", "markdown": "shared text", "audience": "users",
            })
            experiment = experiments.save_experiment(db, self.author, {"title": "Trial", "audience": "users"})
            payload = b"artifact data\n" * 30_000
            experiments.save_item(db, self.author, {
                "experiment_id": experiment, "kind": "data", "title": "Results", "filename": "results.bin", "audience": "users",
            }, payload)
            experiments.save_item(db, self.author, {
                "experiment_id": experiment, "kind": "data", "title": "Private", "filename": "private.bin",
            }, b"secret")
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except PermissionError:
            self.skipTest("Loopback sockets are unavailable")
        with server:
            server.database, server.public_url, server.google_config = self.database, None, None
            work = Thread(target=server.serve_forever)
            work.start()
            try:
                origin = f"http://127.0.0.1:{server.server_port}"
                paths = [self.root / item for item in ("author", "reader", "experiment")]
                for destination, key, route in zip(paths, [*self.keys, self.keys[1]],
                        [f"documents/{document}.git"] * 2 + [f"experiments/{experiment}.git"]):
                    env = {**os.environ, "PAPER_GIT_AUTH": f"Authorization: Bearer {key}"}
                    run = subprocess.run(
                        ["git", "--config-env=http.extraHeader=PAPER_GIT_AUTH", "clone", f"{origin}/git/{route}", destination],
                        env=env, capture_output=True, timeout=30,
                    )
                    self.assertEqual(run.returncode, 0, run.stderr.decode())
                history = subprocess.check_output(["git", "-C", paths[0], "show", "HEAD^:document.md"])
                self.assertEqual(history, b"private draft")
                self.assertEqual((paths[1] / "document.md").read_text(), "shared text")
                self.assertEqual(subprocess.check_output(["git", "-C", paths[1], "rev-list", "--count", "HEAD"]), b"1\n")
                self.api("/api/documents", {
                    "document_id": document, "revision": 2, "title": "Notes", "markdown": "next revision",
                })
                subprocess.run(["git", "-C", paths[0], "--config-env=http.extraHeader=PAPER_GIT_AUTH", "fetch", "origin"],
                               env={**os.environ, "PAPER_GIT_AUTH": f"Authorization: Bearer {self.keys[0]}"},
                               check=True, timeout=30, capture_output=True)
                self.assertEqual(subprocess.check_output(["git", "-C", paths[0], "show", "origin/main:document.md"]),
                                 b"next revision")
                pointers = list(paths[2].glob("artifacts/*/*.paper-pointer.json"))
                self.assertEqual(len(pointers), 1)
                record = json.loads(pointers[0].read_bytes())
                self.assertEqual(record["sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual(record["size"], len(payload))
                self.assertFalse((paths[2] / record["path"]).exists())
                subprocess.run([sys.executable, "-m", "paper_client.artifacts", "--server-url", origin, paths[2]],
                               env={**os.environ, "PAPER_LIBRARY_KEY": self.keys[1]}, check=True, timeout=30, capture_output=True)
                self.assertEqual((paths[2] / record["path"]).read_bytes(), payload)
                self.assertEqual(subprocess.check_output(["git", "-C", paths[2], "status", "--porcelain"]), b"")

                # A reader cannot push. A writer can push each document commit into the browser history.
                (paths[1] / "document.md").write_text("unauthorized edit")
                self.commit(paths[1], "Reader edit")
                self.git(paths[1], "push", key=self.keys[1], success=False)
                self.git(paths[0], "merge", "--ff-only", "origin/main")
                (paths[0] / "document.md").write_text("Git edit one")
                self.commit(paths[0], "First edit")
                (paths[0] / "document.md").write_text("Git edit two")
                git_head = self.commit(paths[0], "Second edit")
                self.git(paths[0], "push", key=self.keys[0])
                document_url = f"/api/document?id={document}"
                browser = self.api(document_url)["document"]
                self.assertEqual((browser["markdown"], browser["revision"]), ("Git edit two", 5))
                self.assertEqual(self.git(paths[0], "ls-remote", "origin", "main", key=self.keys[0]).stdout.split()[0], git_head)
                with library.connect(self.database) as db:
                    self.assertEqual(db.execute(
                        "SELECT markdown FROM document_versions WHERE document_id=? AND revision=4", (document,),
                    ).fetchone()[0], "Git edit one")
                self.api("/api/documents", {
                    "document_id": document, "revision": 5, "title": "Notes", "markdown": "Browser after push",
                })
                self.git(paths[0], "fetch", "origin", key=self.keys[0])
                self.assertEqual(self.git(paths[0], "show", "origin/main^").stdout.splitlines()[0], b"commit " + git_head)
                self.git(paths[0], "merge", "--ff-only", "origin/main")
                (paths[0] / "unrelated.txt").write_text("not a document")
                self.commit(paths[0], "Invalid document tree")
                denied = self.git(paths[0], "push", key=self.keys[0], success=False)
                self.assertIn(b"must contain document.md and document.json", denied.stderr)
                self.assertEqual(self.api(document_url)["document"]["markdown"], "Browser after push")

                # An enrolled agent with an experiment editor grant can push separately from artifact pointers.
                with library.connect(self.database) as db:
                    owner_cookie = accounts.start_session(db, self.author["id"], None)
                code, invitation = request(self.database, "/api/ai/invitations", cookie=owner_cookie,
                                           data={"username": "git-agent", "role": "local"})
                self.assertEqual(code, 200)
                identity = self.root / "agent.json"
                agent.register(identity, "git-agent", origin + invitation["registration_path"])
                self.api("/api/research-grants", {
                    "kind": "experiment", "id": experiment, "readers": [], "editors": ["git-agent"],
                })
                header = subprocess.check_output([sys.executable, "-m", "paper_client.agent", "git-header",
                    "--identity", identity, "--server-url", origin], timeout=30).decode().strip()
                source = self.root / "source"
                url = f"{origin}/git/experiments/{experiment}.git"
                self.git(self.root, "clone", "--branch", "source", url, str(source), header=header)
                (source / "evaluate.py").write_text("print(42)\n")
                (source / "medium.bin").write_bytes(os.urandom(2 * 1024 * 1024))
                agent_head = self.commit(source, "Agent source")
                self.git(source, "-c", "http.postBuffer=65536", "push", header=header)
                self.assertEqual(self.api(f"/api/experiment-detail?id={experiment}")["experiment"]["source_commit"],
                                 agent_head.decode())
                check = self.root / "source-reader"
                self.git(self.root, "clone", "--branch", "source", url, str(check), key=self.keys[1])
                self.assertEqual(self.git(check, "rev-parse", "HEAD").stdout.strip(), agent_head)
                self.assertEqual((check / "evaluate.py").read_text(), "print(42)\n")
                self.assertFalse((check / "experiment.json").exists())
                self.git(paths[2], "fetch", "origin", key=self.keys[1])
                self.assertEqual(self.git(paths[2], "rev-parse", "origin/source").stdout.strip(), agent_head)
                self.git(source, "push", "origin", "HEAD:main", header=header, success=False)
                (source / "oversized.bin").write_bytes(bytes(5 * 1024 * 1024 + 1))
                self.commit(source, "Accidentally add data")
                denied = self.git(source, "push", header=header, success=False)
                self.assertIn(b"Upload large files as experiment artifacts", denied.stderr)
                self.assertEqual(self.git(source, "ls-remote", "origin", "source", header=header).stdout.split()[0], agent_head)
            finally:
                server.shutdown()
                work.join()
