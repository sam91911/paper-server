import json
import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_app import accounts, ai_accounts, library
from paper_client import agent, review
from test_skill_api import request


class AIRegistrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "library.sqlite3"
        library.initialize(self.database)
        with library.connect(self.database) as db:
            accounts.create_account(db, "owner", "owner password", "user")
            self.owner = accounts.create_key(db, 1, "owner")

    def api(self, path, *, expected=200, **options):
        status, result = request(self.database, path, **options)
        self.assertEqual(status, expected, result)
        return result

    def test_recurring_heartbeat_stops_on_authentication_failure(self):
        client = Mock()
        client.request.side_effect = [
            review.LibraryError("Unavailable", 503),
            review.LibraryError("Rate limited", 429),
            b'{"last_heartbeat": 123, "interval_seconds": 60}',
            review.LibraryError("Sign in to continue.", 401),
        ]
        output = io.StringIO()
        with patch.object(agent.time, "sleep") as sleep, redirect_stdout(output), redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(review.LibraryError, "Sign in"):
                agent.send_heartbeats(client)
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual([call.args for call in client.request.call_args_list], [("/api/ai/heartbeat", {})] * 4)
        self.assertEqual(json.loads(output.getvalue())["last_heartbeat"], 123)

    def test_enrollment_replay_and_signed_login(self):
        invitation = {"username": "Researcher", "role": "cloud"}
        self.api("/api/ai/invitations", data=invitation, expected=401)
        route = self.api("/api/ai/invitations", key=self.owner, data=invitation)["registration_path"]
        reviewer = agent.AgentClient(8765, "Researcher", Ed25519PrivateKey.generate())
        body = {"public_key": agent.encode(reviewer.private_key.public_key().public_bytes_raw()),
                "signature": reviewer.sign("register", "Researcher", route)}
        self.api(route, data={**body, "signature": reviewer.sign("register", "AnotherName", route)}, expected=401)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: request(self.database, route, data=body), range(2)))
        self.assertEqual(sorted(status for status, _ in responses), [200, 400])
        challenge = self.api("/api/ai/challenge", data={"username": "researcher"})
        value = challenge["challenge"]
        login = {"username": "researcher", "challenge": value,
                 "signature": reviewer.sign("login", challenge["username"], value)}
        self.api("/api/ai/login", data={**login, "signature": reviewer.sign("login", "Researcher", "other")}, expected=401)
        token = self.api("/api/ai/login", data=login)["access_token"]
        self.api("/api/ai/login", data=login, expected=401)
        self.assertEqual(self.api("/api/account", key=token)["account"]["role"], "cloud")
        self.assertIsNone(self.api("/api/account", cookie=token.removeprefix(accounts.AI_SESSION_PREFIX))["account"])
        self.api("/api/ai/invitations", key=token, data=invitation, expected=403)
        with library.connect(self.database) as db:
            db.execute("UPDATE sessions SET expires=0 WHERE token_hash=?", (accounts.token_hash(token),))
        self.assertIsNone(self.api("/api/account", key=token)["account"])
        with library.connect(self.database) as db:
            accounts.set_role(db, "Researcher", "member")
        self.api("/api/ai/challenge", data={"username": "Researcher"}, expected=401)

    def test_client_persists_key_and_renews_access(self):
        identity = self.database.parent / ".paper-library" / "reviewer.json"
        expired = self.api("/api/ai/invitations", key=self.owner, data={"username": "reviewer", "role": "local"})
        with library.connect(self.database) as db:
            db.execute("UPDATE ai_invites SET expires=0")
        self.assertEqual(self.api("/api/ai/invitations", key=self.owner)["invitations"][0]["status"], "expired")
        active = self.api("/api/ai/invitations", key=self.owner, data={"username": "reviewer", "role": "local"})

        def send(client, route, data=None, **_):
            status, result = request(self.database, route, key=client.key, data=data)
            if status != 200:
                raise review.LibraryError(result["error"], status)
            return json.dumps(result).encode()

        with patch.object(agent.LibraryClient, "request", send):
            with self.assertRaisesRegex(ValueError, "expired"):
                agent.register(identity, "reviewer", "http://127.0.0.1:8765" + expired["registration_path"])
            saved = identity.read_bytes()
            enrolled = agent.register(identity, "reviewer", "http://127.0.0.1:8765" + active["registration_path"])
            self.assertEqual(enrolled["role"], "local")
            self.assertEqual(identity.read_bytes(), saved)
            client = agent.AgentClient.from_identity(identity)
            client.require_role("local")
            first_token = client.key
            client.renew_at = 0
            self.assertIn("skill", client.get_json("/api/skills/default"))
            self.assertNotEqual(first_token, client.key)
        if os.name == "posix":
            self.assertEqual(identity.stat().st_mode & 0o777, 0o600)

    def test_operator_can_manage_agent_owned_items_and_only_inherits_ownership(self):
        with library.connect(self.database) as db:
            worker_id = accounts.create_account(db, "worker", "sample password", "local")
            worker = accounts.create_key(db, worker_id, "worker")
            other_id = accounts.create_account(db, "other", "sample password", "user")
            other = accounts.create_key(db, other_id, "other")
            ai_accounts.assign_operator(db, "worker", "owner")
            paper_id = library.store(db, self.database.with_name("private.pdf"), ((1, "power", "1", "W", "", ""),))
            db.execute("INSERT INTO paper_access VALUES (?,?,'owner')", (paper_id, worker_id))

        shared = self.api("/api/documents", key=other, data={
            "title": "Another user's document", "markdown": "Shared only with worker", "recipients": ["worker"],
        })
        shared_path = f"/api/document?id={shared['document_id']}"
        self.api(shared_path, key=worker)
        self.api(shared_path, key=self.owner, expected=404)

        doc = self.api("/api/documents", key=worker, data={"title": "Private draft", "markdown": "Draft"})
        doc_id = doc["document_id"]
        doc_path = f"/api/document?id={doc_id}"
        self.api(doc_path, key=other, expected=404)
        self.assertTrue(self.api(doc_path, key=self.owner)["document"]["can_manage"])
        change = {"document_id": doc_id, "revision": doc["revision"], "title": "Revised draft", "markdown": "Draft"}
        self.api("/api/documents", key=other, data=change, expected=403)
        revision = self.api("/api/documents", key=self.owner, data=change)["revision"]
        self.assertEqual(self.api(doc_path, key=self.owner)["document"]["owner_id"], worker_id)

        thread = {"document_id": doc_id}
        comment = self.api("/api/comments", key=worker, data={**thread, "body": "A private note"})
        comments = self.api(f"/api/document-comments?document_id={doc_id}", key=self.owner)["comments"]
        self.assertTrue(comments[0]["can_manage"])
        self.assertEqual(comments[0]["author_id"], worker_id)
        self.api("/api/comments", key=self.owner, data={**thread, **comment, "body": "Updated note"})
        self.api("/api/delete-comment", key=self.owner, data={**thread, **comment})

        finding = {**thread, "statement": "A finding", "evidence": [
            {"kind": "document", "id": doc_id, "start": 1, "end": 1, "revision": revision},
        ]}
        recorded = self.api("/api/research-findings", key=worker, data=finding)
        response = self.api(f"/api/research-findings?document_id={doc_id}", key=self.owner)
        self.assertTrue(response["findings"][0]["can_edit"])
        self.api("/api/research-findings", key=self.owner, data={**finding, **recorded, "statement": "Verified"})

        skill = self.api("/api/skills", key=worker, data={"title": "Private skill", "markdown": "Notes"})["skill"]
        self.api("/api/skills", key=self.owner, data={"action": "archive", "id": skill["id"], "revision": skill["revision"]})
        self.assertEqual([row["id"] for row in self.api("/api/skills?archived=1", key=self.owner)["skills"]], [skill["id"]])

        self.assertTrue(self.api(f"/api/paper-detail?paper_id={paper_id}", key=self.owner)["paper"]["can_manage"])
        self.api("/api/metadata", key=self.owner, data={"paper_id": paper_id, "title": "Updated title"})
        self.api("/api/paper-access", key=self.owner, data={"paper_id": paper_id, "audience": "owner"})
        self.assertTrue(self.api(f"/api/paper-metrics?paper_id={paper_id}", key=self.owner)["metrics"][0]["can_edit"])
        self.api("/api/archive-paper", key=self.owner, data={"paper_id": paper_id, "archived": True})
        self.assertEqual([row["id"] for row in self.api("/api/paper-archive", key=self.owner)["papers"]], [paper_id])
        self.api("/api/archive-paper", key=self.owner, data={"paper_id": paper_id, "archived": False})

        self.api("/api/ai/deactivate", key=self.owner, data={"username": "worker"})
        self.api(doc_path, key=worker, expected=401)
        self.api(doc_path, key=self.owner)
        with library.connect(self.database) as db:
            ai_accounts.assign_operator(db, "worker", "other")
        self.api(doc_path, key=self.owner, expected=404)
        self.assertTrue(self.api(doc_path, key=other)["document"]["can_manage"])

    def test_operator_can_edit_agent_created_tasks_without_inheriting_assignments(self):
        with library.connect(self.database) as db:
            worker_id = accounts.create_account(db, "worker", "sample password", "local")
            worker = accounts.create_key(db, worker_id, "worker")
            other_id = accounts.create_account(db, "other", "sample password", "user")
            other = accounts.create_key(db, other_id, "other")
            ai_accounts.assign_operator(db, "worker", "owner")

        route = "/api/tasks"
        task_id = self.api(route, key=worker, data={"title": "Agent task"})["id"]
        assigned_id = self.api(route, key=other, data={"title": "Assigned to worker", "assignee": "worker"})["id"]
        owned = self.api(route, key=self.owner)["tasks"]
        self.assertEqual([task["id"] for task in owned], [task_id])
        self.assertTrue(owned[0]["can_manage"])
        self.api(route, key=self.owner, data={"id": task_id, "revision": 1, "title": "Revised", "due_on": "2027-02-01"})
        edit = {"id": assigned_id, "revision": 1, "status": "closed"}
        self.api(route, key=self.owner, data=edit, expected=403)
        self.api(route, key=worker, data=edit)
        edited = self.api(route, key=self.owner)["tasks"][0]
        self.assertEqual((edited["owner_id"], edited["title"], edited["due_on"]), (worker_id, "Revised", "2027-02-01"))
        with library.connect(self.database) as db:
            ai_accounts.assign_operator(db, "worker", "other")
        self.assertEqual(self.api(route, key=self.owner)["tasks"], [])
        self.api(route, key=self.owner, data={"id": task_id, "revision": 2, "title": "Another edit"}, expected=403)
        self.api(route, key=other, data={"id": task_id, "revision": 2, "title": "New operator"})

    def test_operator_can_cancel_replace_and_rotate_without_changing_account(self):
        route = "/api/ai/invitations"
        with library.connect(self.database) as db:
            account_id = accounts.create_account(db, "another", "other password", "user")
            other = accounts.create_key(db, account_id, "operator")
        enrollment = self.api(route, key=self.owner, data={"username": "Reviewer", "role": "local"})
        old = agent.AgentClient(8765, "Reviewer", Ed25519PrivateKey.generate())

        def register(client, invite, expected=200):
            path = invite["registration_path"]
            return self.api(path, expected=expected, data={
                "public_key": agent.encode(client.private_key.public_key().public_bytes_raw()),
                "signature": client.sign("register", "Reviewer", path),
            })

        def login_body(client):
            challenge = self.api("/api/ai/challenge", data={"username": "reviewer"})["challenge"]
            return {"username": "reviewer", "challenge": challenge,
                    "signature": client.sign("login", "Reviewer", challenge)}

        self.api(route, key=other, data={"action": "cancel", "invite_id": enrollment["invite_id"]}, expected=404)
        self.api(route, key=self.owner, data={"action": "cancel", "invite_id": enrollment["invite_id"]})
        register(old, enrollment, expected=400)
        replacement = self.api(route, key=self.owner, data={"action": "replace", "invite_id": enrollment["invite_id"]})
        original = register(old, replacement)["account"]
        token = self.api("/api/ai/login", data=login_body(old))["access_token"]
        document = self.api("/api/documents", key=self.owner, data={
            "title": "A shared document", "markdown": "Source", "recipients": ["Reviewer"],
        })["document_id"]
        review_id = self.api("/api/reviews", key=self.owner, data={
            "action": "create", "kind": "document", "target_id": document, "agent": "Reviewer", "agent_role": "local",
        })["review"]["id"]
        self.api("/api/reviews", key=token, data={"action": "complete", "id": review_id, "status": "complete", "response": "Review"})
        goal_id = self.api("/api/agent-goals", key=self.owner, data={
            "action": "create", "request_id": "rotation-goal-fixture", "agent": "Reviewer",
            "objective": "Draft a summary", "acceptance_criteria": "Cite the document.",
        })["goal"]["id"]
        pending_challenge = login_body(old)
        self.api(route, key=other, data={"action": "rotate", "username": "Reviewer"}, expected=404)
        rotation = self.api(route, key=self.owner, data={"action": "rotate", "username": "Reviewer"})
        register(old, rotation, expected=400)
        new = agent.AgentClient(8765, "Reviewer", Ed25519PrivateKey.generate())
        self.assertEqual(register(new, rotation)["account"], original)
        self.assertIsNone(self.api("/api/account", key=token)["account"])
        self.api("/api/ai/login", data=pending_challenge, expected=401)
        self.api("/api/ai/login", data=login_body(old), expected=401)
        new_token = self.api("/api/ai/login", data=login_body(new))["access_token"]
        self.assertEqual(self.api(f"/api/reviews?id={review_id}", key=new_token)["review"]["response"], "Review")
        self.assertEqual(self.api(f"/api/document?id={document}", key=new_token)["document"]["title"], "A shared document")
        self.assertEqual(self.api(f"/api/agent-goals?id={goal_id}", key=new_token)["goal"]["id"], goal_id)
        dashboard = self.api(route, key=self.owner)
        self.assertEqual({row["status"] for row in dashboard["invitations"]}, {"canceled", "used"})
        self.assertIsNotNone(dashboard["agents"][0]["last_authenticated"])
        self.assertEqual(self.api(route, key=other), {"invitations": [], "agents": [], "next_before": None})
        with patch.object(ai_accounts, "PAGE_SIZE", 2):
            page = self.api(route, key=self.owner)
            cursor = page["next_before"]
            older = self.api(f"{route}?before={cursor}", key=self.owner)
            self.api(f"{route}?before={cursor}", key=other, expected=404)
        self.assertIsNone(older["next_before"])
        self.assertEqual({row["invite_id"] for row in page["invitations"] + older["invitations"]},
                         {row["invite_id"] for row in dashboard["invitations"]})
        endpoint = "/api/ai/heartbeat"
        self.api(endpoint, key=self.owner, data={}, expected=403)
        self.api(endpoint, data={}, expected=401)
        heartbeat = self.api(endpoint, key=new_token, data={"username": "another"})
        self.assertEqual(heartbeat["interval_seconds"], 60)
        self.assertTrue(self.api(route, key=self.owner)["agents"][0]["online"])
        with patch.object(ai_accounts.time, "time", return_value=heartbeat["last_heartbeat"] + ai_accounts.ONLINE_SECONDS):
            self.assertFalse(self.api(route, key=self.owner)["agents"][0]["online"])

        agent_document = self.api("/api/documents", key=new_token, data={
            "title": "Agent notes", "markdown": "Keep these notes.", "recipients": ["owner"],
        })["document_id"]
        pending_login = login_body(new)
        pending_rotation = self.api(route, key=self.owner, data={"action": "rotate", "username": "Reviewer"})
        with library.connect(self.database) as db:
            application_key = accounts.create_key(db, original["id"], "legacy key")
            browser_session = accounts.start_session(db, original["id"], None)
        deactivate = "/api/ai/deactivate"
        self.api(deactivate, key=other, data={"username": "Reviewer"}, expected=404)
        retired = self.api(deactivate, key=self.owner, data={"username": "Reviewer"})
        self.assertEqual(self.api(deactivate, key=self.owner, data={"username": "Reviewer"}), retired)
        self.api(endpoint, key=new_token, data={}, expected=401)
        self.api(endpoint, key=application_key, data={}, expected=401)
        self.assertIsNone(self.api("/api/account", cookie=browser_session)["account"])
        self.api("/api/ai/login", data=pending_login, expected=401)
        self.api("/api/ai/challenge", data={"username": "Reviewer"}, expected=401)
        register(agent.AgentClient(8765, "Reviewer", Ed25519PrivateKey.generate()), pending_rotation, expected=400)
        self.api(route, key=self.owner, data={"action": "rotate", "username": "Reviewer"}, expected=404)
        stored = self.api(route, key=self.owner)["agents"][0]
        self.assertEqual(stored["disabled_at"], retired["disabled_at"])
        self.assertFalse(stored["online"])
        self.assertEqual(self.api(f"/api/document?id={agent_document}", key=self.owner)["document"]["title"], "Agent notes")
        self.assertEqual(self.api(f"/api/reviews?id={review_id}", key=self.owner)["review"]["response"], "Review")
        self.assertEqual(self.api(f"/api/agent-goals?id={goal_id}", key=self.owner)["goal"]["id"], goal_id)
        self.assertEqual(self.api(f"/api/review-agents?kind=document&target_id={document}", key=self.owner)["agents"], [])
        self.api("/api/agent-goals", key=self.owner, data={
            "action": "create", "request_id": "retired-goal-fixture", "agent": "Reviewer",
            "objective": "Draft a summary", "acceptance_criteria": "Cite the document.",
        }, expected=400)
