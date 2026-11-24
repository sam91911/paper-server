import io
import json
import shutil
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from paper_app import accounts, backup, experiments, integrity, library, server
from scripts import research_pilot


@unittest.skipUnless(shutil.which("pdfinfo") and shutil.which("pdftotext"), "Poppler is not installed")
class ResearchWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "pilot.sqlite3"
        self.pilot = research_pilot.populate(self.database)
        self.document = self.pilot["document"]
        self.route = f"/api/research-findings?document_id={self.document}"
        self.comments = f"/api/document-comments?document_id={self.document}"
        with library.connect(self.database) as db:
            self.browser_token = accounts.start_session(db, 1, None)

    def request(self, route, data=None, *, actor="agent", expected=200, binary=False):
        handler = server.Handler.__new__(server.Handler)
        handler.server = SimpleNamespace(database=self.database, server_port=8765, google_config=None)
        handler.path = route
        handler.command = "GET" if data is None else "POST"
        handler.request_version = "HTTP/1.1"
        handler.requestline = f"{handler.command} {route} HTTP/1.1"
        handler.client_address = ("127.0.0.1", 1)
        handler.headers = Message()
        handler.headers["Host"] = "127.0.0.1:8765"
        if actor == "agent":
            handler.headers["Authorization"] = "Bearer " + self.pilot["ai_key"]
        elif actor == "human":
            handler.headers["Cookie"] = "paper_session=" + self.browser_token
        if data is not None:
            payload = json.dumps(data).encode()
            handler.headers["Content-Type"] = "application/json"
            handler.headers["Content-Length"] = str(len(payload))
            handler.rfile = io.BytesIO(payload)
        handler.wfile = io.BytesIO()
        handler.log_request = lambda *args: None
        (handler.do_GET if data is None else handler.do_POST)()
        header, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        self.assertEqual(int(header.split()[1]), expected, body[:500])
        return body if binary else json.loads(body)

    def test_pilot_comparison_and_agent_reply(self):
        pilot = self.pilot
        self.request(self.route, actor=None, expected=401)
        result = self.request(self.route, actor="human")
        self.assertEqual([row["id"] for row in result["experiments"]], [pilot["experiment"]])
        rows = {row["id"]: row for row in result["findings"]}
        self.assertEqual(rows[pilot["observation"]]["author_role"], "local")
        self.assertEqual(rows[pilot["conclusion"]]["author_role"], "user")
        source, first, second = rows[pilot["conclusion"]]["evidence"]
        self.assertEqual(source["page"], 1)
        self.assertTrue(self.request(source["url"].split("#")[0], binary=True).startswith(b"%PDF"))
        self.assertIn(b"ITEM-9-0", self.request(first["url"], binary=True))
        self.assertIn(b"ITEM-4-O", self.request(second["url"], binary=True))
        for run_id, expected in (("full_run", "10"), ("clean_run", None)):
            result = self.request(f"{self.route}&left={pilot['baseline']}&right={pilot[run_id]}")["comparison"]
            self.assertEqual(result["difference"], expected)
            self.assertEqual(result["reasons"], [] if expected else ["Measurement conditions differ."])
            self.assertEqual([row["value"] for row in result["findings"]], ["80", "90" if expected else "100"])
        root = self.request(self.comments)["comments"][0]
        self.assertEqual(root["finding_id"], pilot["conclusion"])
        reply = self.request("/api/comments", {"document_id": self.document, "parent_id": root["id"],
                                                "body": "Test ambiguous O and 0 separately.", "audience": "local"})
        self.assertEqual(self.request(self.comments, actor="human")["comments"][-1]["id"], reply["comment_id"])
        self.assertEqual(self.request(self.comments, actor="human")["comments"][-1]["author_kind"], "ai")

    def test_revocation_hides_findings_comparison_and_whole_thread(self):
        root = self.request(self.comments)["comments"][0]["id"]
        reply = {"document_id": self.document, "parent_id": root, "body": "Follow-up", "audience": "local"}
        self.request("/api/comments", reply)
        self.request("/api/comments", {"document_id": self.document, "body": "General note", "audience": "local"},
                     actor="human")
        self.request("/api/paper-access", {"paper_id": self.pilot["paper"], "audience": "owner"}, actor="human")
        hidden = {self.pilot["baseline"], self.pilot["conclusion"]}
        self.assertTrue(hidden.isdisjoint(row["id"] for row in self.request(self.route)["findings"]))
        self.request(f"{self.route}&left={self.pilot['baseline']}&right={self.pilot['full_run']}", expected=404)
        self.assertEqual([row["body"] for row in self.request(self.comments)["comments"]], ["General note"])
        legacy = self.request("/api/documents")["comments"]
        self.assertEqual([row["body"] for row in legacy], ["General note"])
        self.request("/api/comments", reply, expected=400)
        self.request("/api/comments", {"document_id": self.document, "finding_id": self.pilot["conclusion"],
                                      "body": "A new thread"}, expected=403)
        self.assertEqual(len(self.request(self.comments, actor="human")["comments"]), 3)
        self.request("/api/documents", {"document_id": self.document, "revision": 1, "title": "Private workspace",
                                        "markdown": "", "audience": "owner"}, actor="human")
        self.request(self.route, expected=404)
        detail = self.request(f"/api/experiment-detail?id={self.pilot['experiment']}")
        self.assertIsNone(detail["experiment"]["research_document_id"])

    def test_stale_document_evidence_can_be_rechecked_by_author(self):
        source = self.request("/api/documents", {"title": "Notes", "markdown": "A\nB\nC", "audience": "local"},
                              actor="human")
        ref = {"kind": "document", "id": source["document_id"], "start": 2, "end": 3, "revision": source["revision"]}
        data = {"document_id": self.document, "statement": "Notes cite B and C.", "evidence": [ref]}
        row = self.request("/api/research-findings", data)
        self.request("/api/documents", {"title": "Notes", "markdown": "A\nUpdated B\nC", "audience": "local", **source},
                     actor="human")
        visible = self.request(self.route)["findings"][0]
        self.assertTrue(visible["evidence"][0]["stale"])
        self.assertNotIn("line=", visible["evidence"][0]["url"])
        self.request("/api/research-findings", {**data, "id": row["id"], "revision": row["revision"]}, expected=409)
        ref["revision"] = 2
        updated = {**data, "id": row["id"], "revision": row["revision"]}
        self.request("/api/research-findings", updated, actor="human", expected=403)
        self.request("/api/research-findings", updated)
        visible = self.request(self.route)["findings"][0]
        self.assertFalse(visible["evidence"][0]["stale"])
        self.assertIn("line=2&end=3&revision=2", visible["evidence"][0]["url"])

    def test_rejects_invalid_sources_and_keeps_original_thread_scope(self):
        ref = {"kind": "pdf", "id": self.pilot["paper"], "page": 2}
        data = {"document_id": self.document, "statement": "Bad source.", "kind": "baseline",
                "evidence": [ref], "verified_baseline": True}
        self.request("/api/research-findings", data, expected=400)
        ref["page"] = 1
        self.request("/api/research-findings", {**data, "verified_baseline": False}, expected=400)
        self.request("/api/research-findings", {**data, "metric": "Accuracy", "value": "NaN"}, expected=400)
        change = {**data, "id": self.pilot["conclusion"], "revision": 1}
        self.request("/api/research-findings", change, actor="human", expected=400)

    def test_backup_and_restore_preserve_evidence_links(self):
        directory = self.database.parent / "backup"
        restored = self.database.with_name("restored.sqlite3")
        backup.create(self.database, directory)
        backup.restore(directory, restored)
        self.database = restored
        library.initialize(restored)
        conclusion = self.request(self.route)["findings"][0]
        for ref in conclusion["evidence"]:
            self.assertTrue(self.request(ref["url"].split("#")[0], binary=True))

    def test_citation_stays_on_the_original_artifact_version(self):
        artifact = self.pilot["runs"][0]["id"]
        url = f"/research-versions/{artifact}/file"
        original = self.request(url, binary=True)
        actor = {"id": 1, "role": "user"}
        with library.connect(self.database) as db:
            item = dict(db.execute(
                "SELECT i.* FROM research_items i JOIN research_versions v ON v.item_id=i.id WHERE v.id=?",
                (artifact,),
            ).fetchone())
            experiments.save_item(db, actor, dict(item, filename="revised.csv"), b"new output")
        self.assertEqual(self.request(url, binary=True), original)
        finding = next(row for row in self.request(self.route)["findings"] if row["id"] == self.pilot["full_run"])
        self.assertEqual(finding["evidence"][0]["url"], url)
        self.request("/api/experiment-runs", {
            "id": item["run_id"], "experiment_id": item["experiment_id"], "revision": 1,
            "title": "Full benchmark", "status": "complete", "audience": "owner",
        }, actor="human")
        self.assertNotIn(finding["id"], {row["id"] for row in self.request(self.route)["findings"]})
        self.assertEqual(self.request(self.comments)["comments"], [])
        self.request(url, expected=404)

    def goal_request(self, action=None, *, actor="agent", expected=200, **data):
        endpoint = "/api/research-goals"
        if action is None:
            return self.request(f"{endpoint}?document_id={self.document}", actor=actor, expected=expected)
        return self.request(endpoint, dict(data, document_id=self.document, action=action),
                            actor=actor, expected=expected)

    def test_goal_api_priorities_briefs_outcomes_and_restore(self):
        self.goal_request(actor=None, expected=401)
        self.assertEqual(self.goal_request()["goals"], [])
        proposals = [
            self.goal_request("propose", question=question, rationale="The source shows a gap.",
                              uncertainty="Is the result reproducible?", evidence_ids=[self.pilot["baseline"]])
            for question in ("Should we inspect misreads?", "Can preprocessing improve accuracy?")
        ]
        chosen = proposals[1]["id"]
        rank = {"goal_id": chosen, "revision": 1, "priority": 1, "selected": True}
        self.goal_request("rank", **rank, expected=403)
        ranked = self.goal_request("rank", **rank, actor="human")
        self.goal_request("rank", **rank, actor="human", expected=409)
        self.assertEqual([row["id"] for row in self.goal_request()["goals"]], [chosen, proposals[0]["id"]])
        draft = self.goal_request(
            "draft", goal_id=chosen, approach="Run exact-match scoring.",
            baseline_id=self.pilot["baseline"], criterion="Reach 90% accuracy.",
            conditions=research_pilot.STANDARD, budget="Ten scans.",
        )
        args = dict(goal_id=chosen, brief_id=draft["brief_id"], revision=ranked["revision"])
        self.goal_request("confirm", **args, expected=403)
        confirmed = self.goal_request("confirm", **args, actor="human")
        self.goal_request("confirm", **args, actor="human", expected=409)
        experiment = confirmed["experiment_id"]
        args["revision"] = confirmed["revision"]
        with library.connect(self.database) as db:
            owner = {"id": 1, "role": "user"}
            planned = experiments.save_run(db, owner, {"title": "Prefilled run", "experiment_id": experiment})
            comparable, matching, artifact = research_pilot.record_external_run(db, owner, self.document, experiment)
            clean, mismatched, _ = research_pilot.record_external_run(db, owner, self.document, experiment, clean=True)
        detail = self.request(f"/api/experiment-detail?id={experiment}", actor="human")
        run = next(row for row in detail["runs"] if row["id"] == planned)
        self.assertEqual(run["methods"], "Run exact-match scoring.")
        self.assertEqual(run["brief_id"], draft["brief_id"])
        outcome = dict(run_id=clean, result_id=mismatched, outcome="met", next_step="design", rationale="Results.")
        self.goal_request("decide", **args, **outcome, expected=403)
        self.goal_request("decide", **args, **outcome, actor="human", expected=400)
        outcome.update(outcome="inconclusive", next_step="iterate")
        inconclusive = self.goal_request("decide", **args, **outcome, actor="human")
        args["revision"] = inconclusive["revision"]
        outcome.update(run_id=comparable, result_id=matching, outcome="met", next_step="design")
        self.goal_request("decide", **args, **outcome, actor="human")
        folder = self.database.parent / "goal-backup"
        restored = self.database.with_name("goal-restored.sqlite3")
        backup.create(self.database, folder)
        backup.restore(folder, restored)
        self.database = restored
        result = self.goal_request(actor="human")["goals"][0]
        self.assertEqual(result["priority"], 1)
        self.assertEqual([row["stage"] for row in result["briefs"]], ["design", "feasibility"])
        decisions = result["briefs"][1]["decisions"]
        self.assertEqual([row["outcome"] for row in decisions], ["met", "inconclusive"])
        self.assertEqual(decisions[0]["evidence"]["comparison"]["difference"], "10")
        self.assertIn("Measurement conditions differ.", decisions[1]["evidence"]["comparison"]["reasons"])
        self.assertIn("## Success criterion", result["briefs"][1]["markdown"])
        self.assertIn(b"ITEM-9-0", self.request(f"/research-versions/{artifact['id']}/file", binary=True))
        design = result["briefs"][0]
        revised = self.goal_request("revise_design", goal_id=chosen, brief_id=design["id"],
                                    revision=result["revision"], baseline_id=self.pilot["baseline"],
                                    approach="Add a second transcription pass.", criterion="Repeat the 90% result.",
                                    conditions=research_pilot.STANDARD, budget="Two local runs.", actor="human")
        full_design = self.goal_request("confirm", goal_id=chosen, brief_id=revised["brief_id"],
                                        revision=result["revision"], actor="human")
        new_brief = self.goal_request()["goals"][0]["briefs"][0]
        self.assertEqual(new_brief["origin_decision_id"], decisions[0]["id"])
        self.assertEqual(new_brief["experiment_id"], full_design["experiment_id"])
        self.assertIn("Two local runs.", new_brief["markdown"])
        with library.connect(self.database) as db:
            final_run, final_result, _ = research_pilot.record_external_run(db, owner, self.document, experiment)
        self.goal_request("decide", actor="human", goal_id=chosen, brief_id=draft["brief_id"],
                          revision=full_design["revision"], run_id=final_run, result_id=final_result, outcome="met",
                          next_step="set_aside", rationale="Prioritize the other question for the next sprint.")
        ordered = self.goal_request(actor="human")["goals"]
        self.assertEqual([row["id"] for row in ordered], [proposals[0]["id"], chosen])
        self.assertTrue(ordered[1]["deferred"])

    def test_goal_evidence_revocation_hides_discussion_experiments_and_artifacts(self):
        chosen = research_pilot.populate_goal_workflow(self.database, self.pilot)
        goals = self.goal_request()["goals"]
        goal = next(row for row in goals if row["id"] == chosen)
        self.assertEqual(len(goals), 2)
        brief = next(row for row in goal["briefs"] if row["confirmed"])
        url = f"/api/experiment-detail?id={brief['experiment_id']}"
        self.request(url)
        root = next(row for row in self.request(self.comments)["comments"] if row["goal_id"] == chosen)
        reply = {"document_id": self.document, "parent_id": root["id"], "body": "Goal reply", "audience": "local"}
        self.request("/api/comments", reply)
        self.request("/api/paper-access", {"paper_id": self.pilot["paper"], "audience": "owner"}, actor="human")
        self.assertNotIn(chosen, {row["id"] for row in self.goal_request()["goals"]})
        self.assertNotIn(root["id"], {row["id"] for row in self.request(self.comments)["comments"]})
        self.assertNotIn("Goal reply", {row["body"] for row in self.request("/api/documents")["comments"]})
        self.request("/api/comments", reply, expected=400)
        self.request(url, expected=404)
        artifact = brief["decisions"][0]["evidence"]["artifacts"][0]["id"]
        self.request(f"/research-versions/{artifact}/file", expected=404)
        self.assertNotIn(brief["experiment_id"], {row["id"] for row in self.request("/api/experiments")["experiments"]})

    def test_agent_controls_goal_access_within_document_and_evidence_access(self):
        fields = {
            "question": "Is a smaller test useful?", "rationale": "Reduce setup time.",
            "uncertainty": "Hardware availability.", "evidence_ids": [self.pilot["baseline"]],
        }
        self.goal_request("propose", expected=400, recipients=[self.pilot["human_username"]], **fields)
        proposal = self.goal_request("propose", audience="owner", **fields)
        goal_id = proposal["id"]
        authored = self.goal_request()["goals"][0]
        self.assertTrue(authored["can_manage"])
        self.assertEqual(authored["revision"], proposal["revision"])
        self.assertEqual(self.goal_request(actor="human")["goals"], [])
        root = self.request("/api/comments", {
            "document_id": self.document, "goal_id": goal_id, "body": "Goal discussion", "audience": "local",
        })
        def discussion_ids():
            return {row["id"] for row in self.request(self.comments, actor="human")["comments"]}

        self.assertNotIn(root["comment_id"], discussion_ids())

        shared = self.goal_request("set_access", goal_id=goal_id, revision=proposal["revision"],
                                   recipients=[self.pilot["human_username"]])
        visible = self.goal_request(actor="human")["goals"][0]
        self.assertEqual(visible["id"], goal_id)
        self.assertNotIn("recipients", visible)
        self.assertIn(root["comment_id"], discussion_ids())
        self.goal_request("set_access", actor="human", goal_id=goal_id, revision=shared["revision"],
                          audience="local", expected=403)
        self.goal_request("set_access", goal_id=goal_id, revision=proposal["revision"], recipients=[], expected=409)
        revoked = self.goal_request("set_access", goal_id=goal_id, revision=shared["revision"], recipients=[])
        self.assertEqual(self.goal_request(actor="human")["goals"], [])
        self.assertNotIn(root["comment_id"], discussion_ids())
        self.goal_request("set_access", goal_id=goal_id, revision=revoked["revision"], audience="inherit")
        self.assertEqual(self.goal_request(actor="human")["goals"][0]["audience"], "inherit")

    def test_integrity_reports_corruption_and_backup_rejects_it(self):
        version = self.pilot["runs"][0]["id"]
        with library.connect(self.database) as db:
            db.execute("UPDATE research_versions SET content=? WHERE id=?", (b"altered", version))
        self.assertEqual(integrity.check(self.database)["changed_artifacts"], [version])
        with self.assertRaisesRegex(ValueError, f"version {version}"):
            backup.create(self.database, self.database.parent / "corrupt-backup")
