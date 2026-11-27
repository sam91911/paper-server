import tempfile
import unittest
from pathlib import Path

from paper_app import accounts, library
from test_skill_api import request


class TagTests(unittest.TestCase):
    def test_tags_filter_across_visible_papers_documents_and_discussions(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "library.sqlite3"
            library.initialize(db_path)
            with library.connect(db_path) as db:
                user = accounts.create_account(db, "owner", "test password", "user")
                viewer = accounts.create_account(db, "viewer", "test password", "user")
                owner, viewer = [accounts.start_session(db, account, None) for account in (user, viewer)]
                paper = library.store(db, Path(folder) / "paper.pdf", ())
                library.save_metadata(db, paper, {"title": "Paper title"})
                library.store(db, Path(folder) / "other.pdf", ())
                db.execute("INSERT INTO paper_access(paper_id,owner_id,audience) VALUES (?,?,'users')", (paper, user))

            def api(route, data=None, *, cookie=owner, expected=200):
                code, result = request(db_path, route, cookie=cookie, data=data)
                self.assertEqual(code, expected, result)
                return result

            api("/api/metadata", {"paper_id": paper, "tags": [" Devices ", "devices", "Data"]})
            detail = api(f"/api/paper-detail?paper_id={paper}", cookie=viewer)["paper"]
            self.assertEqual((detail["title"], detail["tags"]), ("Paper title", ["Data", "Devices"]))
            tagged = api("/api/paper-catalog?tag=DEVICES&facets=1", cookie=viewer)
            self.assertEqual([entry["id"] for entry in tagged["papers"]], [paper])
            self.assertIn("Devices", tagged["tags"])

            draft = {"title": "Notebook", "markdown": "Evidence", "audience": "users", "tags": ["Devices"]}
            doc = api("/api/documents", draft)
            api("/api/documents", {**draft, "title": "Private", "audience": "owner", "tags": ["Private"]})
            thread = api("/api/discussions", {**draft, "title": "Discuss evidence"})
            for route, item in (("documents", doc), ("discussions", thread)):
                items = api(f"/api/{route}?tag=devices", cookie=viewer)["documents"]
                self.assertEqual([entry["id"] for entry in items], [item["document_id"]])
                self.assertEqual(api(f"/api/document?id={item['document_id']}", cookie=viewer)["document"]["tags"], ["Devices"])
            self.assertEqual(api("/api/documents?tag=private", cookie=viewer)["documents"], [])
            api("/api/documents", {**draft, **doc, "tags": []})
            self.assertEqual(api("/api/documents?tag=devices", cookie=viewer)["documents"], [])
            api("/api/metadata", {"paper_id": paper, "tags": ["a,b"]}, expected=400)
