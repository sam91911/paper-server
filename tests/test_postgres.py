import json
import os
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_app import accounts, database, integrity, library, migrate
from paper_client import agent
from scripts import research_pilot
from test_skill_api import request


@unittest.skipUnless(os.getenv("PAPER_TEST_POSTGRES_URL"), "Set PAPER_TEST_POSTGRES_URL to test PostgreSQL")
class PostgreSQLTests(unittest.TestCase):
    def setUp(self):
        from psycopg import connect, sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        self.admin_url = os.environ["PAPER_TEST_POSTGRES_URL"]
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

        def create_target(pdf_dir):
            name = "paper_test_" + uuid4().hex
            with connect(self.admin_url, autocommit=True) as db:
                db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

            def drop():
                with connect(self.admin_url, autocommit=True) as db:
                    db.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))

            self.addCleanup(drop)
            return database.PostgreSQL(make_conninfo(**{**conninfo_to_dict(self.admin_url), "dbname": name}), pdf_dir)

        self.create_target = create_target
        self.target = create_target(self.root / "pdfs")

    def api(self, path, *, expected=200, target=None, **options):
        status, result = request(target or self.target, path, **options)
        self.assertEqual(status, expected, str(result)[:500])
        return result

    def test_ai_registration_and_login(self):
        library.initialize(self.target)
        with library.connect(self.target) as db:
            accounts.create_account(db, "owner", "owner test password", "user")
            cookie = accounts.start_session(db, 1, None)

        username = "PgAgent"
        route = self.api("/api/ai/invitations", cookie=cookie,
                         data={"username": username, "role": "local"})["registration_path"]
        client = agent.AgentClient(8765, username, Ed25519PrivateKey.generate())
        registration = {"public_key": agent.encode(client.private_key.public_key().public_bytes_raw()),
                        "signature": client.sign("register", username, route)}
        self.assertEqual(self.api(route, data=registration)["account"]["role"], "local")
        self.api(route, data=registration, expected=400)
        challenge = self.api("/api/ai/challenge", data={"username": username})["challenge"]
        token = self.api("/api/ai/login", data={"username": username, "challenge": challenge,
                                              "signature": client.sign("login", username, challenge)})["access_token"]
        self.assertEqual(self.api("/api/account", key=token)["account"]["username"], username)

    def test_human_private_key_registration(self):
        library.initialize(self.target)
        private_key = Ed25519PrivateKey.generate()
        challenge = self.api("/api/human-key/challenge", data={"action": "register", "username": "reader"})
        profile = {
            "email": "reader@example.org", "display_name": "Reader", "challenge": challenge["challenge"],
            "public_key": agent.encode(private_key.public_key().public_bytes_raw()),
            "signature": agent.encode(private_key.sign(challenge["message"].encode())),
        }
        account = self.api("/api/human-key/register", data=profile)["account"]
        self.assertIs(account["key_only"], True)
        self.assertEqual(account["role"], "member")
        login = self.api("/api/human-key/challenge", data={"action": "login", "username": "reader"})
        signed = {"challenge": login["challenge"], "signature": agent.encode(private_key.sign(login["message"].encode()))}
        self.assertEqual(self.api("/api/human-key/login", data=signed)["account"], account)

    def test_human_browser_invitation_management(self):
        library.initialize(self.target)
        with library.connect(self.target) as db:
            issuer = accounts.create_account(db, "owner", "sample password", "user")
            cookie = accounts.start_session(db, issuer, None)
        route = "/api/human-invitations"
        invite = self.api(route, cookie=cookie, data={"email": "reader@example.org"})
        pending = self.api(route, cookie=cookie)["invitations"]
        self.assertEqual([item["invite_id"] for item in pending], [invite["invite_id"]])
        self.api(route, cookie=cookie, data={"action": "revoke", "invite_id": invite["invite_id"]})
        self.assertEqual(self.api(route, cookie=cookie)["invitations"], [])

    def test_agent_goal_updates_and_replay(self):
        library.initialize(self.target)
        with library.connect(self.target) as db:
            human = accounts.create_account(db, "owner", "sample password", "user")
            worker = accounts.create_account(db, "worker", "sample password", "local")
            owner = accounts.create_key(db, human, "test")
            client = accounts.create_key(db, worker, "test")
        route = "/api/agent-goals"
        created = self.api(route, key=owner, data={"action": "create", "agent": "worker",
                           "objective": "Inspect a result", "acceptance_criteria": "Explain the issue",
                           "request_id": uuid4().hex})["goal"]
        payload = {"action": "start", "id": created["id"], "revision": created["revision"], "request_id": uuid4().hex}
        started = self.api(route, key=client, data=payload)
        self.assertEqual(self.api(route, key=client, data=payload), started)
        self.assertEqual(self.api(route, key=client)["goals"][0]["status"], "in_progress")

    def test_fresh_library_api_and_concurrent_revision_control(self):
        library.initialize(self.target)
        library.initialize(self.target)
        with library.connect(self.target) as db:
            accounts.create_account(db, "Owner", "password for owner", "user")
            accounts.create_account(db, "local-agent", "password for local", "local")
            accounts.create_account(db, "cloud-agent", "password for cloud", "cloud")
            self.assertEqual(accounts.authenticate(db, "OWNER", "password for owner")["username"], "Owner")
            local = accounts.create_key(db, 2, "local")
            cloud = accounts.create_key(db, 3, "cloud")
            cookie = accounts.start_session(db, 1, None)
            paper = library.store(db, self.root / "Methods.PDF", ((1, "power", "1", "W", "", ""),))
            library.store(db, self.root / "Methods.PDF", ((1, "power", "1", "W", "", ""),))
            library.save_metadata(db, paper, {"title": "Long methods", "year": "0x7e7"})
            db.execute("INSERT INTO paper_access VALUES (?, ?, 'local')", (paper, 1))
            library.create_group(db, "Methods")
            self.assertEqual(db.execute("SELECT id FROM groups WHERE name='METHODS'").fetchone()[0], 1)
            long_evidence = "".join(uuid4().hex for _ in range(150))
            library.store(db, self.root / "Methods.PDF", ((3, "power", "2", "W", "", long_evidence),))
        self.assertEqual(self.api("/api/account", key=local)["account"]["role"], "local")
        self.assertEqual(len(self.api("/api/paper-catalog?q=methods.pdf&from_year=2023&through_year=2023", key=local)["papers"]), 1)
        self.assertEqual(self.api("/api/paper-catalog?q=methods", key=cloud)["papers"], [])
        metrics = self.api("/api/metric-page?after=0", key=local)["metrics"]
        self.assertEqual(len(metrics), 2)
        self.assertEqual(metrics[-1]["evidence"], long_evidence)
        self.api("/api/paper-access", cookie=cookie, data={"paper_id": paper, "audience": "local", "allow_title": True})
        self.assertEqual(self.api(f"/api/paper-detail?paper_id={paper}", key=local)["paper"]["title"], "Long methods")
        metric = self.api(f"/api/paper-metrics?paper_id={paper}", key=local)["metrics"][0]
        self.assertFalse(metric["can_edit"])
        self.api("/api/metric-editors", cookie=cookie, data={
            "action": "grant", "username": "local-agent", "metric_id": metric["id"],
        })
        correction = {field: metric[field] for field in ("revision", "page", "metric", "unit", "conditions", "evidence")}
        correction.update(metric_id=metric["id"], value="3", reason="Verified source table.")
        self.api("/api/paper-metrics", key=local, data=correction)
        self.api("/api/paper-metrics", key=local, data=correction, expected=409)
        self.assertEqual(self.api("/api/metric-page", key=local)["metrics"][0]["value"], "3")
        self.assertIn("3", [row["value"] for row in self.api("/api/compare", key=local)["metrics"]])
        history = self.api(f"/api/metric-history?metric_id={metric['id']}", cookie=cookie)
        self.assertEqual(history["original"]["value"], "1")
        self.assertEqual(history["editors"], ["local-agent"])
        removal = {"metric_id": metric["id"], "revision": 2, "action": "remove", "reason": "Baseline from prior work."}
        self.assertTrue(self.api("/api/paper-metrics", key=local, data=removal)["removed"])
        self.assertEqual([row["value"] for row in self.api("/api/metric-page", key=local)["metrics"]], ["2"])
        self.assertFalse(self.api("/api/paper-metrics", key=local, data={
            **removal, "revision": 3, "action": "restore", "reason": "Verified this paper's result.",
        })["removed"])

        document = self.api("/api/documents", key=local, data={"title": "Notes", "markdown": "Notes", "audience": "all"})
        document_id = document["document_id"]
        self.assertEqual(self.api(f"/api/document?id={document_id}", key=cloud)["document"]["markdown"], "Notes")
        owner_doc = self.api("/api/documents", cookie=cookie,
                             data={"title": "Workspace", "markdown": "Baseline", "audience": "all"})["document_id"]
        queued = self.api("/api/reviews", cookie=cookie, data={
            "action": "create", "kind": "document", "target_id": owner_doc, "agent": "local-agent",
            "agent_role": "local", "post": True,
        })["review"]
        self.assertEqual(self.api("/api/reviews", key=local)["reviews"], [queued])
        result = self.api("/api/reviews", key=local, data={
            "action": "complete", "id": queued["id"], "status": "complete", "response": "Verify the baseline.",
        })["review"]
        self.assertEqual(self.api(f"/api/reviews?id={queued['id']}", cookie=cookie)["review"], result)
        self.assertIsNotNone(result["comment_id"])
        finding = self.api("/api/research-findings", key=local, data={"document_id": owner_doc, "statement": "Control",
                          "evidence": [{"kind": "document", "id": owner_doc, "start": 1, "end": 1, "revision": 1}]})["id"]
        goal = self.api("/api/research-goals", key=local, data={"action": "propose", "document_id": owner_doc,
                        "question": "Test it?", "rationale": "Useful", "uncertainty": "Precision", "evidence_ids": [finding]})
        rank = {"action": "rank", "document_id": owner_doc, "goal_id": goal["id"], "revision": 1,
                "priority": 1, "selected": True}
        self.api("/api/research-goals", key=local, data=rank, expected=403)
        self.assertEqual(self.api("/api/research-goals", cookie=cookie, data=rank)["revision"], 2)
        self.api("/api/comments", key=cloud, data={"document_id": document_id, "body": "Comment", "audience": "all"})
        self.assertEqual(len(self.api(f"/api/document-comments?document_id={document_id}", key=local)["comments"]), 1)
        skill = self.api("/api/skills", key=local, data={"title": "Review rules", "markdown": "Check evidence.",
                         "tags": ["Quality"], "recipients": ["cloud-agent"]})["skill"]
        self.assertEqual(len(self.api("/api/skills?tag=quality", key=cloud)["skills"]), 1)
        self.assertEqual(self.api(f"/api/skills/{skill['id']}", key=cloud)["skill"]["markdown"], "Check evidence.")
        self.api("/api/skills", key=cloud, data={"title": "Cloud skill", "markdown": "Check details."})

        def edit(title):
            payload = {"action": "update", "id": skill["id"], "revision": 1, "title": title,
                       "markdown": skill["markdown"], "recipients": []}
            return request(self.target, "/api/skills", key=local, data=payload)[0]

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(edit, ("First", "Second"))), [200, 409])
        self.api(f"/api/skills/{skill['id']}", key=cloud, expected=404)

        experiment = self.api("/api/experiments", key=local, data={"title": "Trial", "audience": "local"})["id"]
        run = self.api("/api/experiment-runs", key=local, data={"experiment_id": experiment, "title": "Run"})["id"]
        metadata = quote(json.dumps({"experiment_id": experiment, "run_id": run, "title": "Sample", "kind": "data",
                                     "filename": "sample.bin"}))
        self.api("/api/research-upload", key=local, binary=b"\x00data", headers={
            "Content-Type": "application/octet-stream", "X-Research-Metadata": metadata})
        version = self.api(f"/api/experiment-detail?id={experiment}", key=local)["items"][0]["versions"][0]["id"]
        self.assertEqual(self.api(f"/research-versions/{version}/file", key=local), b"\x00data")
        self.api(f"/research-versions/{version}/file", key=cloud, expected=404)

        with library.connect(self.target) as db:
            local_key_id = db.execute("SELECT id FROM application_keys WHERE account_id=2").fetchone()[0]
            local_session = accounts.start_session(db, 2, None)
        self.api("/api/revoke-key", cookie=local_session, data={"key_id": local_key_id})
        self.api("/api/skills", key=local, expected=401)
        self.assertEqual(self.api("/api/account", cookie=cookie)["account"]["role"], "user")

    @unittest.skipUnless(shutil.which("pdfinfo") and shutil.which("pdftotext"), "Poppler is not installed")
    def test_migrate_pilot_and_restore_postgres_backup(self):
        source = self.root / "source.sqlite3"
        pilot = research_pilot.populate(source)
        research_pilot.populate_goal_workflow(source, pilot)
        key = pilot["ai_key"]
        document = pilot["document"]
        findings_path = f"/api/research-findings?document_id={document}"
        goals_path = f"/api/research-goals?document_id={document}"
        comment_path = f"/api/document-comments?document_id={document}"
        expected_findings = self.api(findings_path, target=source, key=key)
        expected_goals = self.api(goals_path, target=source, key=key)
        expected_comments = self.api(comment_path, target=source, key=key)
        migrated_skill = self.api("/api/skills", target=source, key=key, data={
            "title": "Migrated skill", "markdown": "Check the evidence.", "tags": ["Evidence"],
        })["skill"]
        with library.connect(source) as db:
            original_pdf = Path(db.execute("SELECT path FROM papers WHERE id=?", (pilot["paper"],)).fetchone()[0])
            library.store(db, original_pdf, ((1, "manual check", "4", "W", "", ""),))
            owner_id = db.execute("SELECT id FROM accounts WHERE username=?", (pilot["human_username"],)).fetchone()[0]
            cookie = accounts.start_session(db, owner_id, None)
        agent_username = self.api("/api/account", target=source, key=key)["account"]["username"]
        metric_path = f"/api/paper-metrics?paper_id={pilot['paper']}"
        original_metrics = self.api(metric_path, target=source, key=key)["metrics"]
        metric_id = next(row["id"] for row in original_metrics if row["metric"] == "manual check")
        self.api("/api/metric-editors", target=source, cookie=cookie, data={
            "action": "grant", "username": agent_username, "metric_id": metric_id,
        })
        self.api("/api/paper-metrics", target=source, key=key, data={
            "metric_id": metric_id, "revision": 1, "value": "5", "reason": "Reviewed the source.",
        })
        history_path = f"/api/metric-history?metric_id={metric_id}"
        expected_history = self.api(history_path, target=source, cookie=cookie)
        original_bytes = original_pdf.read_bytes()
        original_pdf.unlink()
        with self.assertRaisesRegex(ValueError, "Could not copy the PDF"):
            migrate.migrate(source, self.target)
        self.assertFalse(self.target.pdf_dir.exists())
        original_pdf.write_bytes(original_bytes)

        migrate.migrate(source, self.target)
        with self.assertRaisesRegex(ValueError, "Migration requires"):
            migrate.migrate(source, self.target)
        self.assertEqual(self.api(findings_path, key=key), expected_findings)
        self.assertEqual(self.api(goals_path, key=key), expected_goals)
        self.assertEqual(self.api(comment_path, key=key), expected_comments)
        self.assertEqual(self.api(f"/api/skills/{migrated_skill['id']}", key=key)["skill"], migrated_skill)
        self.assertEqual(self.api(history_path, cookie=cookie), expected_history)
        edited = next(row for row in self.api(metric_path, key=key)["metrics"] if row["id"] == metric_id)
        self.assertEqual((edited["value"], edited["can_edit"]), ("5", True))
        self.assertEqual(self.api(f"/papers/{pilot['paper']}/source.pdf", key=key), original_bytes)
        self.assertTrue(original_pdf.exists())
        self.assertEqual(integrity.check(self.target), {"database_ok": True, "missing": [], "changed": [],
                                                       "orphans": [], "changed_artifacts": []})

        root = expected_comments["comments"][0]["id"]
        reply = self.api("/api/comments", key=key, data={"document_id": document, "parent_id": root, "body": "Migrated thread"})
        self.assertGreater(reply["comment_id"], max(row["id"] for row in expected_comments["comments"]))
        new_document = self.api("/api/documents", key=key, data={"title": "New", "markdown": "After migration"})
        self.assertGreater(new_document["document_id"], document)

        if shutil.which("pg_dump") and shutil.which("pg_restore"):
            target = self.create_target(self.target.pdf_dir)
            dump = self.root / "postgres.dump"
            subprocess.run(["pg_dump", "--format=custom", "--file", str(dump), "--dbname", self.target.url], check=True)
            subprocess.run(["pg_restore", "--exit-on-error", "--single-transaction", "--dbname", target.url, str(dump)], check=True)
            backup_pdfs = self.root / "backup-pdfs"
            shutil.copytree(self.target.pdf_dir, backup_pdfs)
            self.target.pdf_dir.rename(self.root / "cutover-pdfs")
            shutil.copytree(backup_pdfs, target.pdf_dir)
            self.assertEqual(self.api(goals_path, key=key, target=target), expected_goals)
            self.assertEqual(integrity.check(target), integrity.check(self.target))
            self.assertEqual(self.api(f"/papers/{pilot['paper']}/source.pdf", target=target, key=key), original_bytes)
