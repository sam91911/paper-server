import io
import json
import csv
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from paper_app import accounts, library, server


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

    def request(self, route, auth=True, data=None):
        handler = server.Handler.__new__(server.Handler)
        handler.server = SimpleNamespace(database=self.db, server_port=8765, google_config=None)
        handler.path = route
        handler.command = 'GET' if data is None else 'POST'
        handler.request_version = 'HTTP/1.1'
        handler.requestline = handler.command + ' ' + route + ' HTTP/1.1'
        handler.client_address = ('127.0.0.1', 1)
        handler.headers = Message()
        handler.headers['Host'] = '127.0.0.1:8765'
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
        return int(header.split(b' ', 2)[1]), body

    def get(self, route, auth=True):
        return self.request(route, auth)

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
            db.executemany('INSERT INTO metrics VALUES (?,?,?,?,?,?,?)',
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

    def test_csv_export_scopes_and_escapes_cells(self):
        with library.connect(self.db) as db:
            db.execute('INSERT INTO metrics VALUES (?,?,?,?,?,?,?)',
                       (self.papers[0], 1, '=formula', '3', 'W', '', 'evidence'))
        status, payload = self.get('/exports/metrics.csv')
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['metric'], "'=formula")
        self.assertEqual(len(list(csv.DictReader(io.StringIO(self.get('/exports/metrics.csv', False)[1].decode('utf-8-sig'))))), 0)

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
        scripts = ['api.js', 'metrics.js', 'library.js', 'documents.js', 'boot.js']
        positions = [body.index(f'/assets/{name}'.encode()) for name in scripts]
        self.assertEqual(positions, sorted(positions))
        for name in scripts:
            self.assertEqual(self.get('/assets/' + name)[0], 200)

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
