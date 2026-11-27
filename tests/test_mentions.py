import tempfile
import unittest
from pathlib import Path

from paper_app import accounts, library
from test_skill_api import request


class MentionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / "library.sqlite3"
        library.initialize(self.database)
        self.keys = {}
        with library.connect(self.database) as db:
            for username in ("author", "reader", "other"):
                account = accounts.create_account(db, username, "a long password", "user")
                self.keys[username] = accounts.create_key(db, account, username)
            self.paper = library.store(db, Path(temp.name) / "example.pdf", ())
            db.execute("INSERT INTO paper_access(paper_id,owner_id,audience) VALUES (?,1,'users')", (self.paper,))

    def api(self, path, data=None, *, user="author", expected=200):
        code, result = request(self.database, path, key=self.keys.get(user), data=data)
        self.assertEqual(code, expected, result)
        return result

    def test_mentions_follow_sharing_and_edits(self):
        route = "/api/mentions"
        self.api(route, user=None, expected=401)
        note = {"title": "Discuss baseline", "markdown": "@ReAdEr, see the result. Email a@other.",
                "audience": "owner"}
        document = self.api("/api/discussions", note)
        self.assertEqual(self.api(route, user="reader")["mentions"], [])
        document = self.api("/api/discussions", {**note, **document, "recipients": ["reader", "other"]})
        mention = self.api(route, user="reader")["mentions"][0]
        self.assertEqual(mention["url"], f"/discussions?document={document['document_id']}")
        self.assertEqual(self.api(route, user="other")["mentions"], [])
        self.api("/api/discussions", {**note, **document, "markdown": "No mention now."})
        self.assertEqual(self.api(route, user="reader")["mentions"], [])

    def test_paper_reply_mentions_respect_ancestors_and_focus_older_threads(self):
        root = self.api("/api/comments", {"paper_id": self.paper, "body": "Baseline",
                                         "audience": "owner"})["comment_id"]
        comment = self.api("/api/comments", {"paper_id": self.paper, "body": "Check this, @reader.",
                                            "parent_id": root, "audience": "users"})["comment_id"]
        self.assertEqual(self.api("/api/mentions", user="reader")["mentions"], [])
        self.api("/api/comments", {"paper_id": self.paper, "comment_id": root, "body": "Baseline", "audience": "users"})
        self.assertEqual(self.api("/api/mentions", user="reader")["mentions"][0]["url"],
                         f"/papers?paper={self.paper}&comment={comment}#comment-{comment}")
        with library.connect(self.database) as db:
            for _ in range(51):
                library.save_comment(db, self.paper, "Newer thread", {"id": 1, "role": "user"}, audience="users")
        route = f"/api/paper-comments?paper_id={self.paper}"
        recent = self.api(route, user="reader")
        self.assertNotIn(comment, {item["id"] for item in recent["comments"]})
        focused = self.api(f"{route}&focus={comment}", user="reader")
        self.assertIn(comment, {item["id"] for item in focused["comments"]})
        self.assertEqual(focused["next_before"], recent["next_before"])
        self.api("/api/delete-comment", {"paper_id": self.paper, "comment_id": comment})
        self.assertEqual(self.api("/api/mentions", user="reader")["mentions"], [])
