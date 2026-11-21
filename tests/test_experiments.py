import tempfile
import unittest
from pathlib import Path
from paper_app import accounts, experiments, library, sharing


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'data.sqlite3'
        library.initialize(self.path)
        with library.connect(self.path) as db:
            for name, role in [('owner', 'user'), ('editor', 'member'), ('cloud', 'cloud')]:
                db.execute('INSERT INTO accounts(username,password_hash,salt,role,ai_location,trusted) VALUES (?,?,?,?,?,?)',
                           (name, b'h', b's', *accounts.role_fields(role), role == 'user'))
            self.users = {r['username']: {'id': r['id'], 'username': r['username'], 'role': r['effective']}
                          for r in db.execute(f"SELECT a.*, {accounts.ROLE_SQL.format(alias='a')} effective FROM accounts a")}

    def test_parent_and_item_access_and_version_immutability(self):
        with library.connect(self.path) as db:
            owner, editor, cloud = (self.users[n] for n in ('owner', 'editor', 'cloud'))
            exp = experiments.save_experiment(db, owner, {'title': 'Experiment'})
            experiments.set_grants(db, 'experiment', exp, owner, experiments.require_experiment(db, exp, owner), [], ['editor'])
            run = experiments.save_run(db, owner, {'experiment_id': exp, 'title': 'Run'})
            experiments.set_grants(db, 'run', run, owner, experiments.require_run(db, run, owner), [], ['editor'])
            data = {'experiment_id': exp, 'run_id': run, 'kind': 'code', 'title': 'Source', 'filename': 'a.py'}
            item = experiments.save_item(db, owner, data, b'first')
            with self.assertRaises(sharing.AccessDenied):
                experiments.require_item(db, item, editor)
            experiments.set_grants(db, 'item', item, owner, experiments.require_item(db, item, owner), [], ['editor'])
            self.assertEqual(experiments.require_item(db, item, editor, edit=True)['id'], item)
            with self.assertRaises(sharing.AccessDenied):
                experiments.require_item(db, item, cloud)
            experiments.save_item(db, editor, dict(data, id=item, revision=1), b'second')
            versions = db.execute('SELECT id FROM research_versions WHERE item_id=? ORDER BY number', (item,)).fetchall()
            self.assertEqual(experiments.version_content(db, editor, versions[0]['id'])[1], b'first')
            self.assertEqual(experiments.version_content(db, editor, versions[1]['id'])[1], b'second')
            experiments.set_grants(db, 'experiment', exp, owner, experiments.require_experiment(db, exp, owner), [], [])
            with self.assertRaises(sharing.AccessDenied):
                experiments.version_content(db, editor, versions[0]['id'])

    def test_item_parent_mismatch_and_invalid_upload_are_rejected(self):
        with library.connect(self.path) as db:
            owner = self.users['owner']
            first = experiments.save_experiment(db, owner, {'title': 'One'})
            second = experiments.save_experiment(db, owner, {'title': 'Two'})
            run = experiments.save_run(db, owner, {'experiment_id': first, 'title': 'Run'})
            with self.assertRaises(sharing.AccessDenied):
                experiments.save_item(db, owner, {'experiment_id': second, 'run_id': run, 'kind': 'data', 'title': 'Data'})
            with self.assertRaises(ValueError):
                experiments.save_item(db, owner, {'experiment_id': first, 'kind': 'data', 'title': 'Data', 'filename': '../x'}, b'x')

    def test_tool_approval_requires_distinct_authorized_human_and_access(self):
        from paper_app import tools_catalog
        with library.connect(self.path) as db:
            owner, editor = self.users['owner'], self.users['editor']
            db.execute("UPDATE accounts SET trusted=1 WHERE id=?", (editor['id'],))
            editor = dict(editor, role='user')
            db.execute('INSERT INTO tool_approvers VALUES (?)', (editor['id'],))
            exp = experiments.save_experiment(db, owner, {'title': 'Experiment', 'audience': 'users'})
            run = experiments.save_run(db, owner, {'experiment_id': exp, 'title': 'Run', 'audience': 'users'})
            tool = tools_catalog.register(db, owner, {'name': 'Tool', 'audience': 'users',
                'image_digest': 'example/tool@sha256:' + 'a' * 64, 'command': ['/bin/true']})
            job = tools_catalog.create_job(db, owner, {'run_id': run, 'tool_id': tool})
            db.execute('INSERT INTO tool_approvers VALUES (?)', (owner['id'],))
            with self.assertRaises(sharing.AccessDenied):
                tools_catalog.approve_job(db, owner, job)
            tools_catalog.approve_job(db, editor, job)
            self.assertEqual(db.execute('SELECT status FROM tool_jobs WHERE id=?', (job,)).fetchone()[0], 'approved')
            with self.assertRaises(sharing.AccessDenied):
                tools_catalog.approve_job(db, editor, job)
