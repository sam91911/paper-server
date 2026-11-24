import io
import json
import csv
import re
import tempfile
import unittest
from email.message import Message
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_app import accounts, library, server
from paper_client.agent import encode
from paper_client.review import library_origin


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'test.sqlite3'
        library.initialize(self.db)
        with library.connect(self.db) as db:
            db.execute("INSERT INTO accounts(username,password_hash,salt) VALUES ('owner',?,?)", (b'h', b's'))
            account = {'id': 1, 'role': 'user', 'username': 'owner'}
            self.token = accounts.start_session(db, 1, None)
            self.papers = []
            for name in ('one', 'two'):
                paper = library.store(db, '/tmp/' + name + '.pdf', ())
                db.execute('INSERT INTO paper_access VALUES (?,?,?)', (paper, 1, 'owner'))
                library.save_comment(db, paper, name, account)
                self.papers.append(paper)

    def request(self, route, auth=True, data=None, *, headers=None, public_url=None):
        handler = server.Handler.__new__(server.Handler)
        handler.server = SimpleNamespace(database=self.db, server_port=8765, google_config=None, public_url=public_url)
        handler.path = route
        handler.command = 'GET' if data is None else 'POST'
        handler.request_version = 'HTTP/1.1'
        handler.requestline = handler.command + ' ' + route + ' HTTP/1.1'
        handler.client_address = ('127.0.0.1', 1)
        handler.headers = Message()
        for name, value in {'Host': '127.0.0.1:8765', **(headers or {})}.items():
            handler.headers[name] = value
        if data is not None:
            payload = json.dumps(data).encode()
            handler.rfile = io.BytesIO(payload)
            handler.headers['Content-Type'] = 'application/json'
            handler.headers['Content-Length'] = str(len(payload))
        if auth:
            handler.headers['Cookie'] = 'paper_session=' + self.token
        handler.wfile = io.BytesIO()
        handler.log_request = lambda *args: None
        (handler.do_GET if data is None else handler.do_POST)()
        header, body = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
        self.response_headers = Message()
        for line in header.decode('ascii').split('\r\n')[1:]:
            name, value = line.split(':', 1)
            self.response_headers[name] = value.strip()
        return int(header.split(b' ', 2)[1]), body

    def get(self, route, auth=True):
        return self.request(route, auth)

    def test_agent_client_can_be_downloaded_before_registration(self):
        status, payload = self.get("/api/client/download", False)
        self.assertEqual(status, 200)
        self.assertEqual(self.response_headers["Content-Type"], "application/zip")
        self.assertEqual(self.response_headers["Content-Disposition"], 'attachment; filename="paper-client.zip"')
        with ZipFile(io.BytesIO(payload)) as bundle:
            self.assertEqual(set(bundle.namelist()), {
                "paper-client/pyproject.toml", "paper-client/__init__.py", "paper-client/__main__.py",
                "paper-client/agent.py", "paper-client/paper_source.py", "paper-client/review.py",
            })

    def test_health_checks_existing_database_without_creating_a_replacement(self):
        self.assertEqual(self.get("/api/health", False), (200, b'{"status": "ok"}'))
        self.db = self.db.with_name("unavailable.sqlite3")
        self.assertEqual(self.get("/api/health", False), (503, b'{"status": "unavailable"}'))
        self.assertFalse(self.db.exists())

    def test_public_ip_origins_match_browser_host_headers_and_invitation_links(self):
        for value, expected in (
            ("https://192.0.2.44:443/", "https://192.0.2.44"),
            ("https://[2001:DB8:0:0:0:0:0:44]:443/", "https://[2001:db8::44]"),
            ("https://[2001:db8:0::44]:08443", "https://[2001:db8::44]:8443"),
        ):
            with self.subTest(origin=value):
                origin = server.public_url(value)
                self.assertEqual(origin, expected)
                self.assertEqual(library_origin(value), expected)
                headers = {"Host": expected.removeprefix("https://"), "Origin": expected}
                status, response = self.request("/api/ai/invitations", True, {"username": "remote", "role": "local"},
                                                headers=headers, public_url=origin)
                self.assertEqual(status, 200, response)
                invitation = json.loads(response)
                self.assertEqual(invitation["registration_url"], origin + invitation["registration_path"])
                self.assertEqual(invitation["client_download_url"], origin + "/api/client/download")
                self.assertEqual(self.request("/api/health", False, headers={"Host": "other.example.org"},
                                              public_url=origin)[0], 403)

    def test_key_signup_and_sign_in_on_public_origin(self):
        origin = server.public_url("https://Papers.Example.org:443/")
        public = {"Host": "papers.example.org", "Origin": origin}
        private_key = Ed25519PrivateKey.generate()

        def api(path, data=None, *, status=200, headers=public, auth=False):
            result_status, payload = self.request(path, auth, data, headers=headers, public_url=origin)
            self.assertEqual(result_status, status, payload)
            return json.loads(payload)

        def prove(action, *, auth=False):
            body = api("/api/human-key/challenge", {"action": action, "username": "Reader"}, auth=auth)
            return {"challenge": body["challenge"], "signature": encode(private_key.sign(body["message"].encode()))}

        self.assertEqual(api("/api/openapi.json")["servers"], [{"url": origin}])
        api("/api/account", headers={**public, "Origin": "https://another.example.org"}, status=403)
        api("/api/account", headers={"Host": "unconfigured.example.org"}, status=403)
        invitation = api("/api/ai/invitations", {"username": "reviewer", "role": "cloud"}, auth=True)
        self.assertEqual(invitation["registration_url"], origin + invitation["registration_path"])
        self.assertEqual(invitation["client_download_url"], origin + "/api/client/download")
        human_invite = api("/api/human-invitations", {"email": "reader@example.org", "role": "user"}, auth=True)
        self.assertEqual(human_invite["role"], "user")
        self.assertEqual(human_invite["expires_in"], 86400)
        prefix = origin + "/account#invite="
        self.assertTrue(human_invite["invitation_url"].startswith(prefix))
        invite = human_invite["invitation_url"].removeprefix(prefix)
        registration = {**prove("register"), "email": "reader@example.org", "display_name": "Reader",
                        "public_key": encode(private_key.public_key().public_bytes_raw()), "invite": invite}
        api("/api/human-key/register", registration, headers={"Host": "127.0.0.1:8765"}, status=401)
        api("/api/human-key/register", {**registration, "email": "another@example.org"}, status=400)
        account = api("/api/human-key/register", registration)["account"]
        self.assertEqual((account["role"], account["key_only"]), ("user", True))
        self.assertTrue(SimpleCookie(self.response_headers["Set-Cookie"])[accounts.COOKIE]["secure"])
        api("/api/human-key/register", registration, status=401)
        replay = api("/api/register", {"username": "another-reader", "password": "sample new password",
                                       "email": "reader@example.org", "display_name": "Reader", "invite": invite},
                     status=400)
        self.assertIn("valid invitation", replay["error"])
        login = prove("login")
        self.assertEqual(api("/api/human-key/login", login)["account"]["username"], "Reader")
        self.token = SimpleCookie(self.response_headers["Set-Cookie"])[accounts.COOKIE].value
        api("/api/human-key/login", login, status=401)
        api("/api/sign-in", {"username": "Reader", "password": "a random password"}, status=400)
        primary = api("/api/account", auth=True)["sign_in_keys"][0]["key_id"]
        api("/api/human-key/revoke", {"key_id": primary}, auth=True, status=400)

        original, private_key = private_key, Ed25519PrivateKey.generate()
        attachment = {**prove("attach", auth=True), "label": "Backup",
                      "public_key": encode(private_key.public_key().public_bytes_raw())}
        api("/api/human-key/attach", attachment, auth=True)
        self.token = SimpleCookie(self.response_headers["Set-Cookie"])[accounts.COOKIE].value
        self.assertEqual(len(api("/api/account", auth=True)["sign_in_keys"]), 2)
        api("/api/human-key/revoke", {"key_id": primary}, auth=True)
        self.assertIsNone(api("/api/account", auth=True)["account"])
        self.assertEqual(api("/api/human-key/login", prove("login"))["account"]["id"], account["id"])
        private_key = original
        api("/api/human-key/login", prove("login"), status=401)

    def test_human_invitation_issuance_requires_trusted_browser_session(self):
        route = "/api/human-invitations"
        email = {"email": "friend@example.org"}
        with library.connect(self.db) as db:
            member_id = accounts.create_account(db, "member", "sample member password", "member")
            member_token = accounts.start_session(db, member_id, None)
            other_id = accounts.create_account(db, "other-issuer", "sample issuer password", "user")
            other_token = accounts.start_session(db, other_id, None)
            key = accounts.create_key(db, 1, "test")
        self.assertEqual(self.request(route, False, email)[0], 401)
        self.assertEqual(self.request(route, True, email, headers={"Authorization": "Bearer " + key})[0], 401)
        self.assertEqual(self.request(route, False, email, headers={"Cookie": "paper_session=" + member_token})[0], 403)
        self.assertEqual(self.request(route, False, headers={"Cookie": "paper_session=" + member_token})[0], 403)
        self.assertEqual(self.request(route, True, email, headers={"Origin": "https://unrelated.example.org"})[0], 403)
        public = "https://papers.example.org"
        original = json.loads(self.request(route, True, email, public_url=public)[1])
        replacement = json.loads(self.request(route, True, email, public_url=public)[1])
        first, second = original["invitation_url"], replacement["invitation_url"]
        self.assertTrue(first.startswith(public + "/account#invite="))
        self.assertTrue(second.startswith(public + "/account#invite="))
        self.assertNotEqual(first, second)
        with library.connect(self.db) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM human_invites WHERE token_hash=?",
                                         (accounts.token_hash(first.split("=", 1)[1]),)).fetchone())
        pending = json.loads(self.get(route)[1])["invitations"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending, [{"invite_id": replacement["invite_id"], "email": email["email"],
                                    "expires": pending[0]["expires"], "role": "member"}])
        other = {"Cookie": "paper_session=" + other_token}
        self.assertEqual(json.loads(self.request(route, False, headers=other)[1]), {"invitations": []})
        self.assertEqual(self.request(route, False, email, headers=other)[0], 400)
        revoke = {"action": "revoke", "invite_id": replacement["invite_id"]}
        self.assertEqual(self.request(route, False, revoke, headers=other)[0], 404)
        self.assertEqual(self.request(route, True, {"action": "revoke", "invite_id": original["invite_id"]})[0], 404)
        self.assertEqual(self.request(route, True, revoke)[0], 200)
        self.assertEqual(json.loads(self.get(route)[1]), {"invitations": []})
        status, body = self.request("/api/register", False, {**email, "username": "friend", "display_name": "Friend",
                                    "password": "sample new password", "invite": second.split("=", 1)[1]})
        self.assertEqual(status, 400)
        self.assertIn("valid invitation", json.loads(body)["error"])

    def test_default_member_invitation_grants_direct_sharing_only(self):
        route = "/api/human-invitations"
        email = {"email": "friend@example.org"}
        self.assertEqual(self.request(route, True, {**email, "role": "local"})[0], 400)
        status, body = self.request(route, True, email)
        self.assertEqual(status, 200)
        invitation = json.loads(body)
        self.assertEqual(invitation["role"], "member")
        status, body = self.request("/api/register", False, {
            **email, "username": "friend", "display_name": "Friend", "password": "sample new password",
            "invite": invitation["invitation_url"].split("=", 1)[1], "role": "user",
        })
        self.assertEqual(status, 200)
        account = json.loads(body)["account"]
        self.assertEqual(account["role"], "member")
        cookie = self.response_headers["Set-Cookie"].split(";", 1)[0]
        with library.connect(self.db) as db:
            db.execute("UPDATE paper_access SET audience='users' WHERE paper_id=?", (self.papers[1],))
            db.execute("INSERT INTO item_grants VALUES ('paper',?,?)", (self.papers[0], account["id"]))
        self.assertEqual(self.request(f"/api/paper-detail?paper_id={self.papers[0]}", False,
                                      headers={"Cookie": cookie})[0], 200)
        self.assertEqual(self.request(f"/api/paper-detail?paper_id={self.papers[1]}", False,
                                      headers={"Cookie": cookie})[0], 404)

    def test_existing_human_can_attach_a_key_after_sign_in(self):
        private_key = Ed25519PrivateKey.generate()
        route = "/api/human-key/challenge"
        self.assertEqual(self.request(route, False, {"action": "attach"})[0], 401)
        status, payload = self.request(route, True, {"action": "attach"})
        self.assertEqual(status, 200)
        challenge = json.loads(payload)
        proof = {"challenge": challenge["challenge"], "signature": encode(private_key.sign(challenge["message"].encode())),
                 "public_key": encode(private_key.public_key().public_bytes_raw())}
        self.assertEqual(self.request("/api/human-key/attach", False, proof)[0], 401)
        status, payload = self.request("/api/human-key/attach", True, proof)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(payload)["account"]["has_private_key"])
        self.assertFalse(json.loads(payload)["account"]["key_only"])

    def test_scoped_comments_and_legacy_snapshot(self):
        status, response = self.get('/api/paper-details')
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(response)['comments']), 2)
        _, response = self.get('/api/paper-details?comments=none')
        self.assertEqual(json.loads(response)['comments'], [])
        _, response = self.get('/api/paper-comments?paper_id=' + str(self.papers[0]))
        self.assertEqual([c['body'] for c in json.loads(response)['comments']], ['one'])
        _, response = self.get('/api/paper-comments?paper_id=' + str(self.papers[0]), False)
        self.assertEqual(json.loads(response)['comments'], [])
        self.assertEqual(self.get('/api/paper-comments?paper_id=0')[0], 400)
        self.assertIn(b'async function api', self.get('/assets/api.js')[1])

    def test_pagination_keeps_threads_and_checks_cursor(self):
        account = {'id': 1, 'role': 'user', 'username': 'owner'}
        with library.connect(self.db) as db:
            for n in range(55):
                parent = library.save_comment(db, self.papers[0], f'root {n}', account)
                if n == 4:
                    child = library.save_comment(db, self.papers[0], 'reply', account, parent_id=parent)
        _, payload = self.get(f'/api/paper-comments?paper_id={self.papers[0]}')
        page = json.loads(payload)
        roots = [c for c in page['comments'] if c['parent_id'] is None]
        self.assertEqual(len(roots), 50)
        self.assertIsNotNone(page['next_before'])
        self.assertNotIn(child, {c['id'] for c in page['comments']})
        _, payload = self.get(f"/api/paper-comments?paper_id={self.papers[0]}&before={page['next_before']}")
        older = json.loads(payload)
        self.assertIn(child, {c['id'] for c in older['comments']})
        self.assertIsNone(older['next_before'])
        self.assertFalse({c['id'] for c in page['comments']} & {c['id'] for c in older['comments']})
        self.assertEqual(self.get(f'/api/paper-comments?paper_id={self.papers[0]}&before=-1')[0], 400)

    def test_metric_pages_apply_paper_access(self):
        with library.connect(self.db) as db:
            db.executemany('INSERT INTO metrics(paper_id,page,metric,value,unit,conditions,evidence) VALUES (?,?,?,?,?,?,?)',
                           ((self.papers[0], i + 1, 'power', str(i), 'W', '', '') for i in range(510)))
        status, payload = self.get('/api/metric-page')
        self.assertEqual(status, 200)
        first = json.loads(payload)
        self.assertEqual(len(first['metrics']), 500)
        self.assertIsNotNone(first['next_after'])
        _, payload = self.get(f"/api/metric-page?after={first['next_after']}")
        second = json.loads(payload)
        self.assertEqual(len(second['metrics']), 10)
        self.assertIsNone(second['next_after'])
        self.assertTrue(set(x['page'] for x in first['metrics']).isdisjoint(x['page'] for x in second['metrics']))
        self.assertEqual(json.loads(self.get('/api/metric-page', False)[1])['metrics'], [])
        self.assertEqual(self.get('/api/metric-page?after=-1')[0], 400)

    def test_paper_pages_apply_access_and_archiving(self):
        with library.connect(self.db) as db:
            db.executemany('INSERT INTO papers(path) VALUES (?)', ((f'/tmp/bulk-{i}.pdf',) for i in range(105)))
            db.execute("INSERT INTO paper_access SELECT id,1,'owner' FROM papers WHERE id>2")
            db.execute('INSERT INTO archived_papers VALUES (2)')
        first = json.loads(self.get('/api/paper-page')[1])
        self.assertEqual(len(first['papers']), 100)
        self.assertNotIn(2, [p['id'] for p in first['papers']])
        second = json.loads(self.get(f"/api/paper-page?after={first['next_after']}")[1])
        self.assertEqual(len(second['papers']), 6)
        self.assertIsNone(second['next_after'])
        self.assertEqual(json.loads(self.get('/api/paper-page', False)[1])['papers'], [])

    def test_paper_catalog_combines_filters_and_clamps_numbered_pages(self):
        with library.connect(self.db) as db:
            db.execute("UPDATE papers SET title='Énergie 光學%',authors='Ada',venue='Optics',"
                       "year='2021',publisher='Example' WHERE id=1")
            db.execute("UPDATE papers SET title='Énergie 光學', authors='Ada',year='2020unknown',"
                       "publisher='Hidden Archive' WHERE id=2")
            db.execute("INSERT INTO archived_papers VALUES (2)")
            db.execute("INSERT INTO groups VALUES (1,'Optics')")
            db.execute("INSERT INTO memberships VALUES (1,1)")
            # Duplicate paths must have a stable tie-breaker across pages.
            db.executemany("INSERT INTO papers (path,year) VALUES (?,?)", [('/tmp/z.pdf', 'n/a')] * 105)
            db.execute("INSERT INTO paper_access SELECT id,1,'owner' FROM papers WHERE id>2")
        catalog = "/api/paper-catalog?"
        fields = dict(q="ÉNERGIE adA 光學% one.pdf", group=1, publisher="Example",
                      from_year=2020, through_year=2022, facets=1)
        status, payload = self.get(catalog + urlencode(fields))
        self.assertEqual(status, 200)
        result = json.loads(payload)
        self.assertEqual(result['papers'], [{'id': 1, 'path': 'one.pdf', 'title': 'Énergie 光學%'}])
        self.assertEqual((result['count'], result['total'], result['page']), (1, 106, 1))
        self.assertEqual(result['publishers'], ['Example'])
        self.assertEqual(result['groups'], [{'id': 1, 'name': 'Optics'}])
        first = json.loads(self.get(catalog + 'page=1')[1])
        last = json.loads(self.get(catalog + 'page=999')[1])
        self.assertEqual(len(first['papers']), 100)
        self.assertEqual(last['page'], 2)
        self.assertEqual([p['id'] for p in first['papers'] + last['papers']], [1, *range(3, 108)])
        for query in ('q=no-match', 'group=99', 'from_year=2022', 'q=%25%25'):
            empty = json.loads(self.get(catalog + query + '&page=9')[1])
            self.assertEqual((empty['papers'], empty['count'], empty['page']), ([], 0, 1))
        for query in ('page=0', 'group=-2', 'from_year=2025&through_year=2020', 'through_year=abc'):
            self.assertEqual(self.get(catalog + query)[0], 400)

    def test_bounded_paper_reads_preserve_access_and_lazy_lists(self):
        owner_token = self.token
        with library.connect(self.db) as db:
            db.execute("INSERT INTO accounts(username,password_hash,salt,trusted) VALUES ('reader',X'00',X'00',0)")
            reader_token = accounts.start_session(db, 2, None)
            db.execute("UPDATE papers SET sha256='pdf1',publisher='Shared' WHERE id=1")
            db.execute("UPDATE papers SET sha256='pdf2',publisher='Private' WHERE id=2")
            db.execute("INSERT INTO item_grants VALUES ('paper',1,2)")
            db.execute("INSERT INTO groups VALUES (1,'Owner group')")
            db.execute("INSERT INTO memberships VALUES (1,1)")
            db.execute("INSERT INTO paper_metadata_checks (paper_id,allow_title) VALUES (1,1)")
            db.execute("INSERT INTO documents (id,owner_id,audience,title,markdown) "
                       "VALUES (1,1,'owner','Shared document',''),(2,1,'owner','Private document','')")
            db.execute("INSERT INTO item_grants VALUES ('document',1,2)")
            db.execute("INSERT INTO archived_papers VALUES (2)")

        def get_data(route, auth=True):
            status, payload = self.get(route, auth)
            self.assertEqual(status, 200)
            return json.loads(payload)

        catalog = '/api/paper-catalog?facets=1'
        detail = '/api/paper-detail?paper_id=1'
        targets = '/api/paper-comment-targets'
        archive = '/api/paper-archive'
        self.assertEqual(get_data(catalog, False)['publishers'], [])
        self.assertEqual(self.get(detail, False)[0], 404)
        self.assertEqual(get_data(targets, False), {'papers': [], 'documents': []})
        self.assertEqual(get_data(archive)['papers'][0]['id'], 2)
        self.assertEqual(self.get('/api/paper-detail?paper_id=2')[0], 404)
        owner_detail = get_data(detail)
        self.assertEqual(owner_detail['paper']['recipients'], ['reader'])
        self.assertEqual(owner_detail['paper']['allow_title'], 1)
        self.assertEqual(owner_detail['group_ids'], [1])

        self.token = reader_token
        listing = get_data(catalog)
        self.assertEqual(listing['publishers'], ['Shared'])
        self.assertEqual(listing['groups'], [])
        self.assertEqual(get_data(catalog + '&group=1')['count'], 0)
        result = get_data(detail)
        self.assertEqual(result['paper']['path'], 'one.pdf')
        self.assertNotIn('recipients', result['paper'])
        self.assertEqual(result['group_ids'], [])
        self.assertEqual(get_data(archive), {'papers': []})
        self.assertEqual([paper['id'] for paper in get_data(targets)['papers']], [1])
        self.assertEqual(get_data(targets)['documents'], [{'id': 1, 'title': 'Shared document'}])

        self.token = owner_token
        self.assertEqual(self.request('/api/archive-paper', data={'paper_id': 2, 'archived': False})[0], 200)
        self.assertEqual(get_data(archive), {'papers': []})
        self.assertEqual(get_data('/api/paper-detail?paper_id=2')['paper']['id'], 2)

    def test_csv_export_scopes_and_escapes_cells(self):
        with library.connect(self.db) as db:
            db.execute('INSERT INTO metrics(paper_id,page,metric,value,unit,conditions,evidence) VALUES (?,?,?,?,?,?,?)',
                       (self.papers[0], 1, '=formula', '3', 'W', '', 'evidence'))
        status, payload = self.get('/exports/metrics.csv')
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['metric'], "'=formula")
        self.assertEqual(len(list(csv.DictReader(io.StringIO(self.get('/exports/metrics.csv', False)[1].decode('utf-8-sig'))))), 0)

    def test_shared_news_reuses_document_discussions_and_supporting_goals(self):
        with library.connect(self.db) as db:
            account = accounts.create_account(db, "reader-ai", "temporary password", "cloud")
            key = accounts.create_key(db, account, "news test")
        agent = {"Authorization": "Bearer " + key}

        def post(route, data, *, by_agent=False, expected=200):
            status, raw = self.request(route, not by_agent, data, headers=agent if by_agent else None)
            self.assertEqual(status, expected, raw)
            return json.loads(raw)

        self.assertEqual(self.get("/news", False)[0], 200)
        post("/api/documents", {"title": "Lab notes", "markdown": "Private note."})
        source_url = "https://example.org/news/research-update"
        payload = {"title": "Research update", "markdown": "The update reports a new benchmark."}
        for invalid in ("javascript:alert(1)", "http://example.org", "https://user@example.org"):
            post("/api/documents", {**payload, "source_url": invalid}, expected=400)
        entry = post("/api/documents", {**payload, "source_url": source_url, "recipients": ["reader-ai"]})
        identifier = entry["document_id"]
        feed = json.loads(self.request("/api/news", False, headers=agent)[1])["documents"]
        self.assertEqual([(row["id"], row["source_url"]) for row in feed], [(identifier, source_url)])
        self.assertEqual(json.loads(self.get("/api/news", False)[1])["documents"], [])
        comment = post("/api/comments", {"document_id": identifier, "body": "Can we reproduce this benchmark?",
                                        "recipients": ["owner"]}, by_agent=True)
        comments = json.loads(self.get(f"/api/document-comments?document_id={identifier}")[1])["comments"]
        self.assertEqual(comments[0]["id"], comment["comment_id"])
        finding = post("/api/research-findings", {
            "document_id": identifier, "statement": "The announcement describes a new benchmark.",
            "evidence": [{"kind": "document", "id": identifier, "start": 1, "end": 1, "revision": entry["revision"]}],
        }, by_agent=True)
        proposal = post("/api/research-goals", {"action": "propose", "document_id": identifier,
            "question": "Can we reproduce the benchmark?", "rationale": "Check the published claim.",
            "uncertainty": "Public input availability", "evidence_ids": [finding["id"]]}, by_agent=True)
        goals = json.loads(self.get(f"/api/research-goals?document_id={identifier}")[1])["goals"]
        self.assertEqual(goals[0]["id"], proposal["id"])
        post("/api/documents", {**entry, **payload, "recipients": []})
        self.assertEqual(json.loads(self.get(f"/api/document?id={identifier}")[1])["document"]["source_url"], source_url)
        self.assertEqual(json.loads(self.request("/api/news", False, headers=agent)[1])["documents"], [])

    def test_document_update_conflict_through_http(self):
        data = {'title': 'Initial', 'markdown': 'text', 'audience': 'owner'}
        self.assertEqual(self.request('/api/documents', False, data)[0], 401)
        status, body = self.request('/api/documents', True, data)
        self.assertEqual(status, 200)
        created = json.loads(body)
        edit = dict(data, document_id=created['document_id'], revision=created['revision'], title='Updated')
        self.assertEqual(self.request('/api/documents', True, edit)[0], 200)
        self.assertEqual(self.request('/api/documents', True, edit)[0], 409)
        status, body = self.get(f"/api/document?id={created['document_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['document']['title'], 'Updated')

    def test_paper_routes_enforce_access_and_rollback(self):
        paper = self.papers[0]
        data = {'paper_id': paper, 'title': 'Updated title'}
        self.assertEqual(self.request('/api/metadata', False, data)[0], 403)
        self.assertEqual(self.request('/api/metadata', True, data)[0], 200)
        invalid = {'paper_id': paper, 'audience': 'all', 'allow_title': 'yes'}
        self.assertEqual(self.request('/api/paper-access', True, invalid)[0], 400)
        with library.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT title FROM papers WHERE id=?', (paper,)).fetchone()[0], 'Updated title')
            self.assertEqual(db.execute('SELECT audience FROM paper_access WHERE paper_id=?', (paper,)).fetchone()[0], 'owner')

    def test_key_lifecycle_and_sign_out(self):
        status, body = self.request('/api/application-keys', True, {'label': 'test'})
        self.assertEqual(status, 200)
        key = json.loads(body)['key']
        with library.connect(self.db) as db:
            self.assertEqual(accounts.current_account(db, key, application_key=True)['id'], 1)
            key_id = db.execute('SELECT id FROM application_keys').fetchone()[0]
        self.assertEqual(self.request('/api/revoke-key', True, {'key_id': key_id})[0], 200)
        with library.connect(self.db) as db:
            self.assertIsNone(accounts.current_account(db, key, application_key=True))
        self.assertEqual(self.request('/api/sign-out', True, {})[0], 200)
        self.assertIsNone(json.loads(self.get('/api/account')[1])['account'])

    def test_page_scripts_are_available_in_dependency_order(self):
        status, body = self.get('/')
        self.assertEqual(status, 200)
        scripts = ['api.js', 'metrics.js', 'library.js', 'human-keys.js', 'documents.js', 'findings.js', 'goals.js', 'boot.js']
        positions = [body.index(f'/assets/{name}'.encode()) for name in scripts]
        self.assertEqual(positions, sorted(positions))
        for name in scripts:
            self.assertEqual(self.get('/assets/' + name)[0], 200)

    def test_experiments_uses_the_library_page_layout(self):
        status, experiments = self.get('/experiments')
        self.assertEqual(status, 200)
        self.assertIn(b'<header class="page-header"><h1>Experiments</h1>', experiments)
        self.assertIn(b'<main class="page-content" id="workspace-content"', experiments)
        self.assertIn(b'href="#workspace-content">Skip to content', experiments)
        self.assertLess(experiments.index(b'<nav class="workspace-nav"'), experiments.index(b'<main'))

        def navigation(page):
            return re.search(rb'<nav class="workspace-nav"[^>]*>(.*?)</nav>', page, re.S)[1]

        experiment_nav = navigation(experiments)
        self.assertIn(b'<a href="/experiments" aria-current="page">', experiment_nav)
        self.assertEqual(experiment_nav.count(b'aria-current="page"'), 1)
        self.assertEqual(re.findall(rb'href="([^"]+)"', experiment_nav),
                         re.findall(rb'href="([^"]+)"', navigation(self.get('/skills')[1])))

    def test_document_comments_are_scoped_and_backward_compatible(self):
        account = {'id': 1, 'role': 'user', 'username': 'owner'}
        with library.connect(self.db) as db:
            from paper_app import sharing
            first = sharing.save_document(db, account, {'title': 'First', 'markdown': 'one'})
            second = sharing.save_document(db, account, {'title': 'Second', 'markdown': 'two'})
            library.save_comment(db, None, 'first comment', account, document_id=first)
            library.save_comment(db, None, 'second comment', account, document_id=second)
        self.assertEqual(len(json.loads(self.get('/api/documents')[1])['comments']), 2)
        self.assertEqual(json.loads(self.get('/api/documents?comments=none')[1])['comments'], [])
        summary = json.loads(self.get('/api/documents?comments=none&content=summary')[1])
        self.assertTrue(all('markdown' not in doc for doc in summary['documents']))
        self.assertTrue(all('owner_name' in doc and 'revision' in doc for doc in summary['documents']))
        full = json.loads(self.get(f'/api/document?id={first}')[1])['document']
        self.assertEqual(full['markdown'], 'one')
        _, body = self.get(f'/api/document-comments?document_id={first}')
        self.assertEqual([c['body'] for c in json.loads(body)['comments']], ['first comment'])
        self.assertEqual(json.loads(self.get(f'/api/document-comments?document_id={first}', False)[1])['comments'], [])


if __name__ == '__main__':
    unittest.main()
