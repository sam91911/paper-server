import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_app import accounts, library
from paper_client import review
from test_skill_api import request


class ReviewAPITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "reviews.sqlite3"
        library.initialize(self.database)
        with library.connect(self.database) as db:
            for username, role in (("requester", "user"), ("reviewer", "local"),
                                   ("another-ai", "cloud"), ("other-human", "user")):
                db.execute("INSERT INTO accounts(username,password_hash,salt,role,ai_location,trusted) VALUES (?,?,?,?,?,?)",
                           (username, b"hash", b"salt", *accounts.role_fields(role), int(role == "user")))
            self.cookie = accounts.start_session(db, 1, None)
            self.reviewer = accounts.create_key(db, 2, "local")
            self.other_agent = accounts.create_key(db, 3, "cloud")
            self.other_human = accounts.create_key(db, 4, "human")
        self.document = self.api("/api/documents", cookie=self.cookie, data={
            "title": "Methods", "markdown": "First line\nSecond line", "recipients": ["reviewer"],
        })["document_id"]

    def api(self, path, *, status=200, **options):
        result, body = request(self.database, path, **options)
        self.assertEqual(result, status, body)
        return body

    def create(self, **overrides):
        data = {"action": "create", "kind": "document", "target_id": self.document,
                "position": 2, "agent": "reviewer", "agent_role": "local", "post": True}
        return self.api("/api/reviews", cookie=self.cookie, data={**data, **overrides})["review"]

    def test_assigned_review_returns_result_and_posts_at_most_once(self):
        job = self.create()
        self.assertEqual(self.create()["id"], job["id"])
        path = f"/api/reviews?id={job['id']}"
        self.assertEqual(self.api("/api/reviews", key=self.reviewer)["reviews"], [job])
        self.assertEqual(self.api("/api/reviews", key=self.other_agent)["reviews"], [])
        self.api(path, key=self.other_human, status=404)
        payload = {"action": "complete", "id": job["id"], "status": "complete", "response": "Specify the baseline."}
        self.api("/api/reviews", key=self.other_agent, data=payload, status=404)
        saved = self.api("/api/reviews", key=self.reviewer, data=payload)["review"]
        self.assertEqual(saved["status"], "complete")
        self.assertEqual(self.api("/api/reviews", key=self.reviewer, data=payload)["review"], saved)
        self.api("/api/reviews", key=self.reviewer, data={**payload, "response": "Different"}, status=409)
        self.assertEqual(self.api(path, cookie=self.cookie)["review"], saved)
        self.assertEqual(self.api("/api/reviews", key=self.reviewer)["reviews"], [])
        discussion = f"/api/document-comments?document_id={self.document}"
        self.assertEqual(self.api(discussion, cookie=self.cookie)["comments"], [])
        comments = self.api(discussion, key=self.reviewer)["comments"]
        self.assertEqual([(row["id"], row["target_position"]) for row in comments], [(saved["comment_id"], 2)])

    def test_source_revocation_hides_assignment_and_blocks_completion(self):
        self.api("/api/reviews", cookie=self.cookie, status=400, data={
            "action": "create", "kind": "document", "target_id": self.document,
            "agent": "another-ai", "agent_role": "cloud",
        })
        job = self.create()
        self.api("/api/documents", cookie=self.cookie, data={
            "document_id": self.document, "revision": 1, "title": "Methods", "markdown": "First line\nSecond line",
            "recipients": [],
        })
        self.assertEqual(self.api("/api/reviews", key=self.reviewer)["reviews"], [])
        self.api(f"/api/reviews?id={job['id']}", cookie=self.cookie, status=404)
        self.api("/api/reviews", key=self.reviewer, status=403, data={
            "action": "complete", "id": job["id"], "status": "complete", "response": "No longer accessible.",
        })

    def test_thread_supplies_only_selected_comment_and_parents(self):
        def comment(body, parent_id=None, recipients=()):
            return self.api("/api/comments", cookie=self.cookie, data={
                "document_id": self.document, "body": body, "parent_id": parent_id, "recipients": list(recipients),
            })["comment_id"]

        parent = comment("Parent", recipients=["reviewer"])
        selected = comment("Selected", parent, ["reviewer"])
        comment("Sibling", parent, ["reviewer"])
        job = self.create(kind="thread", target_id=selected, position=None, post=False)
        path = f"/api/reviews?id={job['id']}"
        self.assertNotIn("thread", self.api(path, cookie=self.cookie)["review"])
        self.assertEqual(self.api(path, key=self.reviewer)["review"]["thread"], [
            {"id": selected, "body": "Selected"}, {"id": parent, "body": "Parent"},
        ])

    def test_review_choices_require_access_to_the_whole_thread(self):
        self.api("/api/documents", cookie=self.cookie, data={
            "document_id": self.document, "revision": 1, "title": "Methods", "markdown": "First line",
            "recipients": ["reviewer", "another-ai"],
        })
        parent = self.api("/api/comments", cookie=self.cookie, data={
            "document_id": self.document, "body": "Parent", "recipients": ["reviewer"],
        })["comment_id"]
        selected = self.api("/api/comments", cookie=self.cookie, data={
            "document_id": self.document, "parent_id": parent, "body": "Selected",
            "recipients": ["reviewer", "another-ai"],
        })["comment_id"]
        path = f"/api/review-agents?kind=thread&target_id={selected}"
        result = self.api(path, cookie=self.cookie)
        self.assertEqual(result["agents"], [{"username": "reviewer", "role": "local", "display_name": ""}])
        self.api(path, key=self.other_human, status=403)
        self.api(path, key=self.reviewer, status=403)
        self.api(path, status=401)

    def test_paper_review_defaults_to_page_one_and_failure_does_not_post(self):
        with library.connect(self.database) as db:
            paper = library.store(db, self.database.parent / "source.pdf", (), "a" * 64)
            db.execute("INSERT INTO paper_access VALUES (?,1,'owner')", (paper,))
            db.execute("INSERT INTO item_grants VALUES ('paper',?,2)", (paper,))
        job = self.create(kind="paper", target_id=paper, position=None)
        self.assertEqual(job["position"], 1)
        failed = self.api("/api/reviews", key=self.reviewer, data={
            "action": "complete", "id": job["id"], "status": "failed", "response": "Could not extract text.",
        })["review"]
        self.assertIsNone(failed["comment_id"])
        self.assertEqual(self.api(f"/api/paper-comments?paper_id={paper}", key=self.reviewer)["comments"], [])

    def test_default_skill_describes_review_api(self):
        skill = self.api("/api/skills/default", key=self.reviewer)["skill"]
        self.assertIn("GET /api/reviews", skill["markdown"])
        self.assertIn("Authorization: Bearer", skill["markdown"])
        self.api("/api/skills/default", status=401)
        paths = self.api("/api/openapi.json")["paths"]
        self.assertIn("/api/skills/default", paths)
        self.assertIn("post", paths["/api/reviews"])


class ReviewWorkerTests(unittest.TestCase):
    def test_worker_reads_assigned_context_and_returns_model_result(self):
        client = Mock()
        client.get_json.side_effect = [
            {"review": {"status": "pending", "kind": "document", "target_id": 3, "position": 2}},
            {"document": {"title": "Methods", "markdown": "One\nTwo"}},
        ]
        with patch.object(review, "review", return_value="Check the baseline.") as model:
            review.complete_assignment(client, 7, SimpleNamespace(cloud=False, model=Path("test.gguf")), {})
        model.assert_called_once_with(Path("test.gguf"), "Document: Methods\n\nOne\nTwo")
        self.assertEqual([call.args[0] for call in client.get_json.call_args_list],
                         ["/api/reviews?id=7", "/api/document?id=3"])
        client.request.assert_called_once_with("/api/reviews", {
            "action": "complete", "id": 7, "status": "complete", "response": "Check the baseline.",
        })
