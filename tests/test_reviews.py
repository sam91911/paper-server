import hashlib
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_app import accounts, library, reviews
from paper_client import review
from test_pdf_integration import fixture_pdf
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
        self.assertEqual(self.api(f"/api/reviews?id={job['id']}", cookie=self.cookie)["review"], job)
        self.api("/api/reviews", key=self.reviewer, status=403, data={
            "action": "complete", "id": job["id"], "status": "complete", "response": "No longer accessible.",
        })
        withdrawn = self.api("/api/reviews", cookie=self.cookie, data={"action": "withdraw", "id": job["id"]})
        self.assertEqual(withdrawn["review"]["status"], "withdrawn")

    def test_only_requester_can_withdraw_and_no_result_is_posted(self):
        job = self.create()
        route = "/api/reviews"
        payload = {"action": "withdraw", "id": job["id"]}
        self.api(route, key=self.reviewer, data=payload, status=404)
        self.api(route, key=self.other_human, data=payload, status=404)
        withdrawn = self.api(route, cookie=self.cookie, data=payload)["review"]
        self.assertEqual(withdrawn["status"], "withdrawn")
        self.assertEqual(self.api(route, cookie=self.cookie, data=payload)["review"], withdrawn)
        self.assertEqual(self.api(route, key=self.reviewer)["reviews"], [])
        self.assertEqual(self.api(f"{route}?id={job['id']}", key=self.reviewer)["review"], withdrawn)
        self.api(route, key=self.reviewer, data={
            "action": "complete", "id": job["id"], "status": "complete", "response": "Late result",
        }, status=409)
        comments = self.api(f"/api/document-comments?document_id={self.document}", key=self.reviewer)
        self.assertEqual(comments["comments"], [])
        self.assertNotEqual(self.create()["id"], job["id"])

    def test_withdrawal_and_completion_race_has_one_winner(self):
        job = self.create()
        route = "/api/reviews"
        with ThreadPoolExecutor(max_workers=2) as pool:
            withdrawal = pool.submit(request, self.database, route, cookie=self.cookie,
                                     data={"action": "withdraw", "id": job["id"]})
            completion = pool.submit(request, self.database, route, key=self.reviewer,
                                     data={"action": "complete", "id": job["id"], "status": "complete", "response": "Use a baseline."})
        withdrawn, completed = withdrawal.result(), completion.result()
        self.assertEqual(sorted([withdrawn[0], completed[0]]), [200, 409])
        saved = self.api(f"{route}?id={job['id']}", cookie=self.cookie)["review"]
        self.assertEqual(saved["status"], "withdrawn" if withdrawn[0] == 200 else "complete")
        self.assertEqual(saved["comment_id"] is None, withdrawn[0] == 200)

    def test_legacy_pending_review_can_be_withdrawn_after_migration(self):
        job = self.create()
        with library.connect(self.database) as db:
            legacy = reviews.REVIEW_TABLE.format(table="legacy_review_requests").replace(",'withdrawn'", "")
            db.execute(legacy)
            db.execute("INSERT INTO legacy_review_requests SELECT * FROM review_requests")
            db.execute("DROP TABLE review_requests")
            db.execute("ALTER TABLE legacy_review_requests RENAME TO review_requests")
            for column in ("end_page", "whole_pdf", "source_format"):
                db.execute(f"ALTER TABLE review_requests DROP COLUMN {column}")
        library.initialize(self.database)
        self.assertEqual(self.api("/api/reviews", key=self.reviewer)["reviews"], [job])
        result = self.api("/api/reviews", cookie=self.cookie, data={"action": "withdraw", "id": job["id"]})
        self.assertEqual(result["review"]["status"], "withdrawn")

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

    @unittest.skipUnless(shutil.which("pdfinfo") and shutil.which("pdftotext"), "Poppler is not installed")
    def test_pdf_ranges_and_whole_document_text_require_assignment_access(self):
        payload = fixture_pdf(b"Page one", b"Page two", b"Page three")
        path = self.database.parent / "source.pdf"
        path.write_bytes(payload)
        with library.connect(self.database) as db:
            paper = library.store(db, path, (), hashlib.sha256(payload).hexdigest())
            db.execute("INSERT INTO paper_access VALUES (?,1,'owner')", (paper,))
            db.execute("INSERT INTO item_grants VALUES ('paper',?,2)", (paper,))
        options = {"kind": "paper", "target_id": paper, "source_format": "text"}
        range_review = self.create(**options, position=2, end_page=3)
        self.assertEqual(self.create(**options, position=2, end_page=3)["id"], range_review["id"])
        whole = self.create(**options, position=None, whole_pdf=True)
        self.assertNotEqual(range_review["id"], whole["id"])
        self.assertIsNone(whole["position"])
        query = f"/api/reviews?id={range_review['id']}&context=text"
        self.api(query, cookie=self.cookie, status=404)
        self.api(query, key=self.other_agent, status=404)
        text = self.api(query, key=self.reviewer)["text"]
        self.assertEqual(text, "PDF page 2\n\nPage two\n\nPDF page 3\n\nPage three")
        whole_path = f"/api/reviews?id={whole['id']}&context=text"
        self.assertIn("PDF page 1\n\nPage one", self.api(whole_path, key=self.reviewer)["text"])
        self.api("/api/reviews", cookie=self.cookie, status=400, data={
            **options, "action": "create", "agent": "reviewer", "agent_role": "local", "position": 2, "end_page": 4,
        })
        completed = self.api("/api/reviews", key=self.reviewer, data={
            "action": "complete", "id": whole["id"], "status": "complete", "response": "Check the baseline.",
        })["review"]
        comments = self.api(f"/api/paper-comments?paper_id={paper}", key=self.reviewer)["comments"]
        self.assertEqual([(item["id"], item["target_position"]) for item in comments],
                         [(completed["comment_id"], None)])
        self.api(whole_path, key=self.reviewer, status=404)
        with library.connect(self.database) as db:
            db.execute("DELETE FROM item_grants WHERE kind='paper' AND item_id=? AND account_id=2", (paper,))
        self.api(query, key=self.reviewer, status=403)

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


    def test_worker_fetches_text_without_downloading_the_pdf_and_reviews_every_section(self):
        client = Mock()
        context = "First section " * 1000 + "\n" + "Last section " * 1000
        client.get_json.side_effect = [
            {"review": {"id": 7, "status": "pending", "kind": "paper", "target_id": 3, "position": None,
                        "whole_pdf": True, "source_format": "text"}},
            {"text": context},
        ]
        with patch.object(review, "review", return_value="Check the baseline.") as model:
            review.complete_assignment(client, 7, SimpleNamespace(cloud=False, model=Path("test.gguf")), {})
        self.assertEqual([call.args[0] for call in client.get_json.call_args_list],
                         ["/api/reviews?id=7", "/api/reviews?id=7&context=text"])
        excerpts = [call.args[1] for call in model.call_args_list]
        self.assertTrue(all(len(excerpt) <= review.CONTEXT_LIMIT for excerpt in excerpts))
        self.assertIn("First section", excerpts[0])
        self.assertIn("Last section", excerpts[-2])
        self.assertIn("Review notes covering the selected source", excerpts[-1])
        client.request.assert_called_once_with("/api/reviews", {
            "action": "complete", "id": 7, "status": "complete", "response": "Check the baseline.",
        })
