import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_app import accounts, library, server
from paper_client import review


def request(database, path, *, key=None, cookie=None, data=None, binary=None, headers=None):
    handler = server.Handler.__new__(server.Handler)
    handler.server = SimpleNamespace(database=database, server_port=8765, google_config=None)
    handler.path = path
    handler.command = "POST" if data is not None or binary is not None else "GET"
    handler.requestline = f"{handler.command} {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.client_address = ("127.0.0.1", 1)
    handler.connection = SimpleNamespace(settimeout=lambda _: None)
    handler.headers = Message()
    handler.headers["Host"] = "127.0.0.1:8765"
    if key:
        handler.headers["Authorization"] = "Bearer " + key
    if cookie:
        handler.headers["Cookie"] = accounts.COOKIE + "=" + cookie
    if data is not None:
        binary = json.dumps(data).encode()
        handler.headers["Content-Type"] = "application/json"
    if binary is not None:
        handler.headers["Content-Length"] = str(len(binary))
        handler.rfile = io.BytesIO(binary)
    for name, value in (headers or {}).items():
        handler.headers[name] = value
    handler.wfile = io.BytesIO()
    handler.log_request = lambda *args: None
    (handler.do_POST if handler.command == "POST" else handler.do_GET)()
    raw_headers, payload = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    status = int(raw_headers.split()[1])
    if b"Content-Type: application/json;" in raw_headers:
        payload = json.loads(payload)
    return status, payload


class SkillAPITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / "skills.sqlite3"
        library.initialize(self.database)
        with library.connect(self.database) as db:
            for username, role in (("human", "user"), ("local-agent", "local"), ("cloud-agent", "cloud")):
                accounts.create_account(db, username, "a long test password", role)
            self.human = accounts.start_session(db, 1, None)
            self.local = accounts.create_key(db, 2, "local")
            self.cloud = accounts.create_key(db, 3, "cloud")

    def test_skill_permissions_search_and_lifecycle(self):
        path = "/api/skills"
        self.assertEqual(request(self.database, path)[0], 401)
        create = {"title": "Read 100% OCR", "description": "Summarize glyphs", "markdown": "# Review\nCheck the lines.",
                  "tags": ["OCR", "ocr"], "recipients": ["cloud-agent"]}
        status, created = request(self.database, path, key=self.local, data=create)
        self.assertEqual(status, 200, created)
        skill = created["skill"]
        self.assertEqual(skill["audience"], "owner")
        self.assertEqual(skill["tags"], ["OCR"])
        self.assertEqual(skill["recipients"], ["cloud-agent"])
        detail_path = f"{path}/{skill['id']}"
        self.assertEqual(request(self.database, detail_path, cookie=self.human)[0], 404)
        status, items = request(self.database, path + "?q=100%25&tag=OcR", key=self.cloud)
        self.assertEqual(status, 200)
        self.assertEqual([row["id"] for row in items["skills"]], [skill["id"]])
        self.assertNotIn("markdown", items["skills"][0])
        _, detail = request(self.database, detail_path, key=self.cloud)
        self.assertEqual(detail["skill"]["markdown"], create["markdown"])
        self.assertNotIn("recipients", detail["skill"])
        change = {**create, "action": "update", "id": skill["id"], "revision": 1, "recipients": []}
        self.assertEqual(request(self.database, path, key=self.cloud, data=change)[0], 403)
        self.assertEqual(request(self.database, path, key=self.local, data=change)[0], 200)
        self.assertEqual(request(self.database, path, key=self.local, data=change)[0], 409)
        self.assertEqual(request(self.database, detail_path, key=self.cloud)[0], 404)

        archive = {"action": "archive", "id": skill["id"], "revision": 2}
        self.assertEqual(request(self.database, path, key=self.local, data=archive)[0], 200)
        self.assertEqual(request(self.database, path, key=self.local)[1]["skills"], [])
        archived = request(self.database, path + "?archived=1", key=self.local)[1]["skills"]
        self.assertEqual([row["id"] for row in archived], [skill["id"]])
        self.assertEqual(request(self.database, path + "?archived=1", key=self.cloud)[1]["skills"], [])
        self.assertEqual(request(self.database, path, key=self.local,
                                 data={**archive, "action": "restore", "revision": 3})[0], 200)
        self.assertEqual(request(self.database, path, key=self.cloud,
                                 data={"title": "Cloud method", "markdown": "Compare comments."})[0], 200)
        self.assertEqual(request(self.database, path, cookie=self.human,
                                 data={"title": "Human method", "markdown": "Read results."})[0], 200)

    def test_paging_and_openapi(self):
        with library.connect(self.database) as db:
            db.executemany("INSERT INTO skills(owner_id,audience,title,description,markdown,tags,search_text) "
                           "VALUES (2,'owner',?,'','Instructions','[]','sample')", ((f"Sample {n}",) for n in range(51)))
        path = "/api/skills"
        page = request(self.database, path, key=self.local)[1]
        self.assertEqual(len(page["skills"]), 50)
        tail = request(self.database, f"{path}?after={page['next_after']}", key=self.local)[1]
        self.assertEqual(len(tail["skills"]), 1)
        self.assertIsNone(tail["next_after"])

        status, spec = request(self.database, "/api/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(spec["components"]["securitySchemes"]["ApplicationKey"]["scheme"], "bearer")
        self.assertIn("post", spec["paths"][path])
        self.assertIn("get", spec["paths"]["/api/skills/{skill_id}"])
        self.assertEqual(request(self.database, "/skills")[0], 200)


class ReviewSkillTests(unittest.TestCase):
    def test_document_review_fetches_only_the_selected_document(self):
        client = Mock()
        client.get_json.return_value = {"document": {"title": "Methods", "markdown": "One\nTwo"}}
        context, payload = review.document_context(client, 7, 2)
        client.get_json.assert_called_once_with("/api/document?id=7")
        self.assertEqual(context, "Document: Methods\n\nOne\nTwo")
        self.assertEqual(payload, {"document_id": 7, "location": {"kind": "document", "id": 7, "position": 2}})

    def test_review_routes_use_explicit_skill(self):
        skill = {"title": "Quality checklist", "markdown": "Check the results.", "archived": False}
        for flags, mode in ((["--model", "local.gguf"], "review"), (["--cloud"], "cloud_review")):
            with self.subTest(mode=mode), patch.object(review, "LibraryClient") as client_type, \
                 patch.object(review, "review_context", return_value=("research data", {})), \
                 patch.object(review, mode, return_value="Comment") as call_model, \
                 patch("sys.argv", ["paper_client", "--document", "1", "--skill", "3", *flags]), \
                 patch.dict("os.environ", {"PAPER_APP_KEY": "test"}), patch("builtins.print"):
                client = client_type.return_value
                client.get_json.return_value = {"skill": skill}
                review.main()
                client.get_json.assert_called_once_with("/api/skills/3")
                self.assertEqual(call_model.call_args.kwargs, {"skill": skill})
                self.assertIn(skill["markdown"], review.review_instructions(skill))

    def test_cloud_confirmation_names_selected_skill(self):
        skill = {"title": "Quality checklist", "markdown": "Check the results."}
        with patch.dict("os.environ", {"PAPER_AI_CLOUD_URL": "https://example.org/v1/chat/completions",
                                      "PAPER_AI_CLOUD_MODEL": "test"}), \
             patch("builtins.input", return_value="cancel") as confirmation, \
             patch.object(review, "build_opener") as opener:
            with self.assertRaisesRegex(ValueError, "Cloud review canceled"):
                review.cloud_review("data", skill=skill)
        self.assertIn(skill["title"], confirmation.call_args.args[0])
        opener.assert_not_called()
