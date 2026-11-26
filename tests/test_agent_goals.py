import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from paper_app import accounts, agent_goals, ai_accounts, backup, library
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
            for username, role in (("owner", "user"), ("writer", "member"), ("worker", "local"), ("other", "cloud"),
                                   ("outsider", "local"), ("another-owner", "user"), ("unmanaged", "cloud")):
                account = accounts.create_account(db, username, "sample password", role)
                self.keys[username] = accounts.create_key(db, account, "test")

            ai_accounts.assign_operator(db, "worker", "owner")
            ai_accounts.assign_operator(db, "other", "owner")
            ai_accounts.assign_operator(db, "outsider", "another-owner")

    def test_goal_creation_requires_the_operator_of_every_agent(self):
        self.api(user=None, data=self.assignment(), expected=401)
        for user in ("writer", "worker", "another-owner"):
            self.api(user=user, data=self.assignment(), expected=403)
        self.api(data=self.assignment(agent="unmanaged"), expected=403)
        payload = self.assignment(agents=["worker", "outsider"])
        del payload["agent"]
        self.api(data=payload, expected=403)
        self.assertEqual(self.api()["goals"], [])
        self.assertEqual(self.api(user="another-owner", data=self.assignment(agent="outsider"))["goal"]["agent"],
                         "outsider")

    def test_owner_can_delegate_and_revoke_goal_posting(self):
        route = "/api/ai/goal-delegates"
        payload = {"action": "grant", "agent": "worker", "username": "writer"}
        self.api(route, user="another-owner", data=payload, expected=404)
        self.api(route, data={**payload, "username": "other"}, expected=400)
        self.api(route, data=payload)
        self.api(route, data=payload)
        self.assertEqual(self.api(user="writer")["assignable_agents"], ["worker"])
        managed = self.api("/api/ai/invitations")["agents"]
        self.assertEqual(next(agent for agent in managed if agent["username"] == "worker")["goal_delegates"],
                         ["writer"])
        goal = self.api(user="writer", data=self.assignment())["goal"]
        self.assertEqual(goal["requester"], "writer")
        self.assertEqual(self.action(goal, "start")["goal"]["status"], "in_progress")
        self.api(user="writer", data=self.assignment(agent="other"), expected=403)
        self.api(route, user="writer", data={**payload, "username": "another-owner"}, expected=403)
        self.api("/api/ai/deactivate", user="writer", data={"username": "worker"}, expected=403)
        self.api(route, data={**payload, "action": "revoke"})
        self.api(user="writer", data=self.assignment(), expected=403)
        self.assertEqual(self.api(user="writer")["assignable_agents"], [])
        self.assertEqual(self.api(f"{ROUTE}?id={goal['id']}", user="writer")["goal"]["id"], goal["id"])

        self.api(route, data=payload)
        with library.connect(self.database) as db:
            ai_accounts.assign_operator(db, "worker", "another-owner")
        self.assertNotIn("worker", self.api()["assignable_agents"])
        self.assertEqual(self.api(user="writer")["assignable_agents"], [])
        self.api(user="writer", data=self.assignment(), expected=403)

    def api(self, route=ROUTE, *, user="owner", data=None, expected=200):
        code, result = request(self.database, route, key=self.keys.get(user), data=data)
        self.assertEqual(code, expected, result)
        return result

    def document(self, title, **data):
        return self.api("/api/documents", data={"title": title, "markdown": "Evidence", **data})

    def assignment(self, **extra):
        return {"action": "create", "request_id": uuid4().hex, "agent": "worker",
                "objective": "Write a baseline report", "acceptance_criteria": "Cite a source", **extra}

    def test_document_link_to_agent_goal_follows_the_allowlist(self):
        source = self.document("Data", audience="all")["document_id"]
        goal = self.api(data=self.assignment(sources=[{"kind": "document", "id": source}]))["goal"]["id"]
        document = self.document("Goal notes", audience="all", agent_goal_id=goal)["document_id"]
        route = f"/api/document?id={document}"
        self.assertEqual(self.api(route, user="worker")["document"]["goal_link"]["url"], f"/agent-goals?id={goal}")
        self.assertNotIn("goal_link", self.api(route, user="outsider")["document"])

    def test_allowlist_search_suggests_active_ai_accounts(self):
        with library.connect(self.database) as db:
            accounts.create_account(db, "work-human", "sample password", "member")
            accounts.create_account(db, "work-inactive", "sample password", "cloud")
            db.execute("UPDATE accounts SET disabled_at=1 WHERE username='work-inactive'")
        query = "/api/usernames?q=work&role=ai"
        self.assertEqual([row["username"] for row in self.api(query)], ["worker"])
        self.assertEqual([row["username"] for row in self.api("/api/usernames?q=work")], ["work-human", "worker"])

    def test_required_skill_is_fetchable_by_each_allowed_agent(self):
        skill = self.api("/api/skills", data={"title": "Benchmark procedure", "markdown": "Run the local benchmark.",
                                             "recipients": ["worker"]})["skill"]
        payload = self.assignment(agents=["worker", "other"], required_skill_ids=[skill["id"]])
        del payload["agent"]
        self.api(data=payload, expected=400)
        skill = self.api("/api/skills", data={"action": "update", "id": skill["id"], "revision": skill["revision"],
                                             "title": skill["title"], "markdown": skill["markdown"],
                                             "recipients": ["worker", "other"]})["skill"]
        goal = self.api(data=payload)["goal"]
        path = f"{ROUTE}?id={goal['id']}"
        for agent in ("worker", "other"):
            required = self.api(path, user=agent)["goal"]["required_skills"]
            self.assertEqual(required, [{"id": skill["id"], "api_path": f"/api/skills/{skill['id']}",
                                        "title": skill["title"], "revision": skill["revision"]}])
            self.assertEqual(self.api(required[0]["api_path"], user=agent)["skill"]["markdown"], skill["markdown"])
        self.api(path, user="outsider", expected=404)
        self.api(required[0]["api_path"], user="outsider", expected=404)
        self.api("/api/skills", data={"action": "archive", "id": skill["id"], "revision": skill["revision"]})
        self.api(path, user="worker", expected=404)
        self.assertTrue(self.api(path)["goal"]["source_unavailable"])

    def action(self, goal, action, *, user="worker", expected=200, **extra):
        return self.api(user=user, expected=expected, data={
            "id": goal["id"], "revision": goal["revision"], "action": action, "request_id": uuid4().hex, **extra,
        })

    def test_continuous_goal_waits_for_requester_approval_each_round(self):
        payload = self.assignment(continuous=True, require_approval=True, agents=["worker", "other"])
        del payload["agent"], payload["acceptance_criteria"]
        goal = self.api(data=payload)["goal"]
        queue = f"{ROUTE}?work=ready"
        self.assertEqual(self.api(queue, user="worker")["goals"], [])
        self.assertEqual(goal["status"], "paused")
        self.assertEqual(goal["acceptance_criteria"], "")
        self.action(goal, "start", expected=409)
        self.action(goal, "approve", expected=409)
        self.action(goal, "approve", user="another-owner", expected=404)
        goal = self.action(goal, "approve", user="owner")["goal"]
        self.assertEqual([item["id"] for item in self.api(queue, user="worker")["goals"]], [goal["id"]])
        goal = self.action(goal, "start")["goal"]
        self.assertEqual(self.api(queue, user="other")["goals"], [])
        self.assertEqual(self.api(queue, user="worker")["goals"][0]["status"], "in_progress")
        goal = self.action(goal, "submit", note="First round complete")["goal"]
        self.assertEqual(self.api(queue, user="worker")["goals"], [])
        self.assertEqual(goal["status"], "submitted")
        self.action(goal, "start", expected=409)
        self.action(goal, "progress", note="Next round", expected=409)
        self.action(goal, "accept", user="owner", expected=409)
        goal = self.action(goal, "approve", user="owner", note="Compare the paper's baselines")["goal"]
        self.assertEqual(self.api(queue, user="worker")["goals"][0]["status"], "assigned")
        detail = self.api(f"{ROUTE}?id={goal['id']}&before=2", user="worker")
        self.assertEqual([event["action"] for event in detail["events"]], ["create"])
        self.assertEqual(detail["last_submission"]["note"], "First round complete")
        self.assertEqual(detail["last_approval"]["note"], "Compare the paper's baselines")
        self.action(goal, "start", user="other", expected=409)
        goal = self.action(goal, "start")["goal"]
        goal = self.action(goal, "finish", user="owner")["goal"]
        self.assertEqual(goal["status"], "completed")
        self.assertEqual(self.api(queue, user="worker")["goals"], [])
        self.action(goal, "progress", note="Extra work", expected=409)

    def test_continuous_goal_can_start_another_round_without_approval(self):
        self.api(data=self.assignment(acceptance_criteria=""), expected=400)
        self.api(data=self.assignment(continuous="true"), expected=400)
        goal = self.api(data=self.assignment(continuous=True, acceptance_criteria=""))["goal"]
        goal = self.action(goal, "start")["goal"]
        goal = self.action(goal, "submit", note="Round complete")["goal"]
        self.assertEqual(goal["status"], "assigned")
        self.assertEqual(goal["actions"], ["start"])
        self.assertEqual(self.api(f"{ROUTE}?work=ready", user="worker")["goals"][0]["id"], goal["id"])
        self.assertEqual(self.api(f"{ROUTE}?id={goal['id']}", user="worker")["last_submission"]["note"], "Round complete")

    def test_inbox_distinguishes_manual_pause_and_stalled_research(self):
        inbox = f"{ROUTE}?work=attention"
        goal = self.api(data=self.assignment(continuous=True, require_approval=True))["goal"]
        self.assertEqual(self.api(inbox)["goals"][0]["attention"], "approval")
        goal = self.action(goal, "approve", user="owner")["goal"]
        goal = self.action(goal, "pause", user="owner")["goal"]
        self.assertEqual(self.api(inbox)["goals"], [])
        self.assertEqual(goal["actions"], ["resume", "finish", "cancel"])
        goal = self.action(goal, "resume", user="owner")["goal"]
        research = {"findings": "No new evidence", "uncertainty": "Limited sample", "next_step": "Check another baseline"}
        for round_number in range(3):
            goal = self.action(goal, "start")["goal"]
            result = self.action(goal, "submit", research=research)
            self.assertEqual(result["last_submission"]["research"], research)
            goal = result["goal"]
            if round_number < 2:
                goal = self.action(goal, "approve", user="owner")["goal"]
        self.assertEqual(goal["attention"], "stalled")
        self.assertEqual(self.api(inbox)["goals"][0]["id"], goal["id"])
        self.action(goal, "start", expected=409)
        goal = self.action(goal, "retry", user="owner", note="Use the expanded dataset")["goal"]
        self.assertEqual(goal["status"], "assigned")
        self.assertEqual(self.api(inbox)["goals"], [])

    def test_repeated_blocker_requires_human_direction(self):
        goal = self.api(data=self.assignment(continuous=True))["goal"]
        for note in ("Missing source", "missing SOURCE", "Missing  source"):
            goal = self.action(goal, "start")["goal"]
            goal = self.action(goal, "block", note=note)["goal"]
        self.assertEqual(goal["attention"], "stalled")
        self.action(goal, "start", expected=409)
        self.action(goal, "retry", user="owner", expected=400)

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

    def test_allowlisted_agents_can_read_and_take_turns_claiming_a_goal(self):
        payload = self.assignment(agents=["worker", "other"])
        del payload["agent"]
        restricted = self.document("Only the local agent can read this", recipients=["worker"])
        self.api(data={**payload, "sources": [{"kind": "document", "id": restricted["document_id"]}]}, expected=400)
        source = self.document("Shared source", recipients=["worker", "other"])
        goal = self.api(data={**payload, "sources": [{"kind": "document", "id": source["document_id"]}]})["goal"]
        self.assertIsNone(goal["agent"])
        self.assertEqual(goal["agents"], ["other", "worker"])
        path = f"{ROUTE}?id={goal['id']}"
        for reader in ("worker", "other"):
            self.assertEqual(self.api(user=reader)["goals"][0]["actions"], ["start"])
            self.assertEqual(self.api(path, user=reader)["goal"]["objective"], payload["objective"])
        self.assertEqual(self.api(user="outsider")["goals"], [])
        self.api(path, user="outsider", expected=404)

        def claim(reader):
            status, result = request(self.database, ROUTE, key=self.keys[reader], data={
                "action": "start", "id": goal["id"], "revision": goal["revision"], "request_id": uuid4().hex,
            })
            return status, reader, result

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = sorted(pool.map(claim, ("worker", "other")))
        self.assertEqual([status for status, _, _ in claims], [200, 409])
        (_, claimant, result), (_, reader, _) = claims
        goal = result["goal"]
        self.assertEqual(goal["agent"], claimant)
        self.assertEqual(self.api(path, user=reader)["goal"]["actions"], [])
        self.action(goal, "progress", user=reader, note="Cannot update this claim", expected=409)
        private_evidence = self.document("Evidence for the claimant", recipients=[claimant])
        evidence_ref = {"kind": "document", "id": private_evidence["document_id"]}
        goal = self.action(goal, "progress", user=claimant, note="Private citation", evidence=[evidence_ref])["goal"]
        self.assertTrue(self.api(path, user=reader)["events"][0]["redacted"])

        goal = self.action(goal, "release", user="owner")["goal"]
        self.assertIsNone(goal["agent"])
        self.assertEqual(self.action(goal, "start", user=reader)["goal"]["agent"], reader)

        self.api("/api/documents", data={"document_id": source["document_id"], "revision": source["revision"],
                                        "title": "Shared source", "markdown": "Evidence", "recipients": [reader]})
        self.api(path, user=claimant, expected=404)
        self.assertEqual(self.api(path, user=reader)["goal"]["objective"], payload["objective"])

    def test_legacy_sqlite_goals_keep_claims_and_history_after_migration(self):
        goal = self.api(data=self.assignment())["goal"]
        self.action(goal, "start")
        with library.connect(self.database) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            old_table = agent_goals.GOAL_TABLE.format(table="old_agent_goals")
            db.execute(old_table.replace("agent_id INTEGER REFERENCES", "agent_id INTEGER NOT NULL REFERENCES")
                       .replace("agent_role TEXT CHECK", "agent_role TEXT NOT NULL CHECK"))
            db.execute("INSERT INTO old_agent_goals SELECT * FROM agent_goals")
            db.execute("DROP TABLE agent_goal_readers")
            db.execute("DROP TABLE agent_goals")
            db.execute("ALTER TABLE old_agent_goals RENAME TO agent_goals")
        library.initialize(self.database)
        path = f"{ROUTE}?id={goal['id']}"
        record = self.api(path, user="worker")
        self.assertEqual(record["goal"]["agents"], ["worker"])
        self.assertEqual(record["goal"]["agent"], "worker")
        self.assertEqual(record["events"][0]["action"], "start")
        self.api(path, user="other", expected=404)

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
