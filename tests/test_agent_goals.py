import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from paper_app import accounts, backup, library
from test_skill_api import request


ROUTE = "/api/agent-goals"


class AgentGoalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "library.sqlite3"
        library.initialize(self.database)
        self.keys = {}
        with library.connect(self.database) as db:
            for username, role in (("owner", "user"), ("writer", "member"), ("worker", "local"), ("other", "cloud")):
                account = accounts.create_account(db, username, "sample password", role)
                self.keys[username] = accounts.create_key(db, account, "test")

    def api(self, route=ROUTE, *, user="owner", data=None, expected=200):
        code, result = request(self.database, route, key=self.keys.get(user), data=data)
        self.assertEqual(code, expected, result)
        return result

    def document(self, title, **data):
        return self.api("/api/documents", data={"title": title, "markdown": "Evidence", **data})

    def assignment(self, **extra):
        return {"action": "create", "request_id": uuid4().hex, "agent": "worker",
                "objective": "Write a baseline report", "acceptance_criteria": "Cite a source", **extra}

    def action(self, goal, action, *, user="worker", expected=200, **extra):
        return self.api(user=user, expected=expected, data={
            "id": goal["id"], "revision": goal["revision"], "action": action, "request_id": uuid4().hex, **extra,
        })

    def test_lifecycle_permissions_and_idempotency(self):
        shared = self.document("Report", recipients=["worker"])
        private = self.document("Private")
        shared_ref = {"kind": "document", "id": shared["document_id"]}
        private_ref = {"kind": "document", "id": private["document_id"]}
        self.api(user="worker", data=self.assignment(), expected=403)
        self.api(data=self.assignment(sources=[private_ref]), expected=400)
        payload = self.assignment(sources=[shared_ref])
        goal = self.api(data=payload)["goal"]
        self.assertEqual(self.api(data=payload)["goal"], goal)
        self.api(data={**payload, "objective": "different"}, expected=409)
        detail = f"{ROUTE}?id={goal['id']}"
        self.assertEqual(self.api(user="other")["goals"], [])
        self.api(detail, user="other", expected=404)
        self.api(detail, user="writer", expected=404)
        self.action(goal, "start", user="other", expected=404)
        self.action(goal, "start", user="owner", expected=409)

        def claim(_):
            return request(self.database, ROUTE, key=self.keys["worker"], data={
                "action": "start", "id": goal["id"], "revision": goal["revision"], "request_id": uuid4().hex,
            })

        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = sorted(pool.map(claim, range(2)), key=lambda result: result[0])
        self.assertEqual([status for status, _ in claimed], [200, 409])
        goal = claimed[0][1]["goal"]
        self.action(goal, "progress", note="Evidence", evidence=[private_ref], expected=400)
        progress = self.action(goal, "progress", note="Read the baseline", evidence=[shared_ref])
        self.assertEqual(progress["events"][0]["evidence"], [shared_ref])
        goal = self.action(progress["goal"], "block", note="Waiting for a metric")["goal"]
        goal = self.action(goal, "pause", user="owner")["goal"]
        self.action(goal, "start", expected=409)
        goal = self.action(goal, "resume", user="owner")["goal"]
        goal = self.action(goal, "start")["goal"]
        submitted = self.action(goal, "submit", note="Report complete", evidence=[shared_ref])
        self.assertEqual(submitted["goal"]["status"], "submitted")
        self.assertEqual(self.api(detail, user="worker")["events"][0]["note"], "Report complete")
        self.action(submitted["goal"], "accept", expected=409)
        accepted = self.action(submitted["goal"], "accept", user="owner")
        self.assertEqual(accepted["goal"]["status"], "completed")
        self.action(accepted["goal"], "cancel", user="owner", expected=409)

    def test_revoked_sources_hide_goal_and_revoked_evidence_hides_note(self):
        source = self.document("Reference", recipients=["worker"])
        evidence = self.document("Evidence", recipients=["worker"])
        goal = self.api(data=self.assignment(sources=[{"kind": "document", "id": source["document_id"]}]))["goal"]
        goal = self.action(goal, "start")["goal"]
        goal = self.action(goal, "progress", note="Evidence details",
                           evidence=[{"kind": "document", "id": evidence["document_id"]}])["goal"]
        self.api("/api/documents", data={"document_id": evidence["document_id"], "revision": evidence["revision"],
                                        "title": "Evidence", "markdown": "Private now", "recipients": []})
        path = f"{ROUTE}?id={goal['id']}"
        recent = self.api(path, user="worker")["events"][0]
        self.assertTrue(recent["redacted"])
        self.assertEqual(recent["note"], "")
        self.api("/api/documents", data={"document_id": source["document_id"], "revision": source["revision"],
                                        "title": "Reference", "markdown": "Private now", "recipients": []})
        self.api(path, user="worker", expected=404)
        masked = self.api(path)
        self.assertTrue(masked["goal"]["source_unavailable"])
        self.assertNotIn("objective", masked["goal"])
        self.assertEqual(self.action(masked["goal"], "cancel", user="owner")["goal"]["status"], "canceled")

    def test_linked_research_goal_and_progress_survive_restore(self):
        source = self.document("Research notebook", recipients=["worker"])
        document_id = source["document_id"]
        finding = self.api("/api/research-findings", data={"document_id": document_id, "statement": "Study the evidence",
                           "evidence": [{"kind": "document", "id": document_id, "start": 1, "end": 1,
                                         "revision": source["revision"]}]})["id"]
        research_goal = self.api("/api/research-goals", data={"action": "propose", "document_id": document_id,
                                 "question": "What changed?", "rationale": "Verify the baseline",
                                 "uncertainty": "Effect of the control", "evidence_ids": [finding]})["id"]
        goal = self.api(data=self.assignment(sources=[{"kind": "research_goal", "id": research_goal}]))["goal"]
        self.assertEqual(goal["sources"], [{"kind": "research_goal", "id": research_goal, "document_id": document_id}])
        goal = self.action(goal, "start")["goal"]
        self.action(goal, "progress", note="Read supporting evidence", evidence=[{"kind": "finding", "id": finding}])

        snapshot = self.database.with_name("backup")
        restored = self.database.with_name("restored.sqlite3")
        backup.create(self.database, snapshot)
        backup.restore(snapshot, restored)
        self.database = restored
        record = self.api(f"{ROUTE}?id={goal['id']}", user="worker")
        self.assertEqual(record["goal"]["status"], "in_progress")
        self.assertEqual(record["events"][0]["note"], "Read supporting evidence")
        self.assertEqual(record["events"][0]["evidence"][0]["document_id"], document_id)
