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
            for name, role in [('owner', 'user'), ('editor', 'member'), ('cloud', 'cloud'),
                               ('human', 'user'), ('local', 'local')]:
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

    def test_read_visibility_and_owner_only_grant_names(self):
        with library.connect(self.path) as db:
            owner = self.users['owner']
            audiences = ('owner', 'users', 'local', 'all', 'ai')
            experiment_ids = {audience: experiments.save_experiment(
                db, owner, {'title': audience, 'audience': audience},
            ) for audience in audiences}
            experiment_id = experiment_ids['all']
            experiments.set_grants(
                db, 'experiment', experiment_id, owner,
                experiments.require_experiment(db, experiment_id, owner),
                ['local', 'cloud'], ['editor'],
            )
            run_ids = {audience: experiments.save_run(
                db, owner, {'experiment_id': experiment_id, 'title': audience, 'audience': audience},
            ) for audience in audiences}
            experiments.set_grants(
                db, 'run', run_ids['users'], owner, experiments.require_run(db, run_ids['users'], owner),
                ['editor'], [],
            )
            item_ids = {audience: experiments.save_item(db, owner, {
                'experiment_id': experiment_id, 'run_id': run_ids[audience], 'kind': 'data', 'title': audience,
                'audience': 'all',
            }) for audience in audiences}
            experiments.set_grants(
                db, 'item', item_ids['users'], owner, experiments.require_item(db, item_ids['users'], owner),
                [], ['editor'],
            )
            experiments.set_grants(
                db, 'item', item_ids['owner'], owner, experiments.require_item(db, item_ids['owner'], owner),
                ['editor'], [],
            )
            private_item = experiments.save_item(db, owner, {
                'experiment_id': experiment_id, 'run_id': run_ids['all'], 'kind': 'data', 'title': 'Private',
            })

            expected = {
                'owner': (audiences, audiences),
                'editor': (('all',), ('users',)),
                'human': (('users', 'local', 'all'), ('users', 'local', 'all')),
                'local': (('local', 'all', 'ai'), ('local', 'all', 'ai')),
                'cloud': (('all',), ('all',)),
            }
            self.assertEqual(experiments.visible_experiments(db, None), [])
            for username, (visible_experiments, visible_runs) in expected.items():
                with self.subTest(username=username):
                    viewer = self.users[username]
                    listing = experiments.visible_experiments(db, viewer)
                    detail = experiments.detail(db, viewer, experiment_id)
                    self.assertEqual([e['id'] for e in listing],
                                     sorted((experiment_ids[a] for a in visible_experiments), reverse=True))
                    self.assertEqual([r['id'] for r in detail['runs']],
                                     sorted((run_ids[a] for a in visible_runs), reverse=True))
                    items = [item_ids[a] for a in visible_runs]
                    if username == 'owner':
                        items.append(private_item)
                        self.assertEqual(detail['experiment']['readers'], ['cloud', 'local'])
                        self.assertEqual(detail['experiment']['editors'], ['editor'])
                        self.assertEqual(next(r for r in detail['runs'] if r['id'] == run_ids['users'])['readers'],
                                         ['editor'])
                        self.assertEqual(next(i for i in detail['items'] if i['id'] == item_ids['users'])['editors'],
                                         ['editor'])
                    else:
                        for row in [*listing, detail['experiment'], *detail['runs'], *detail['items']]:
                            self.assertNotIn('readers', row)
                            self.assertNotIn('editors', row)
                        with self.assertRaises(sharing.AccessDenied):
                            experiments.detail(db, viewer, experiment_ids['owner'])
                    self.assertEqual([i['id'] for i in detail['items']], sorted(items, reverse=True))

    def test_experiment_reads_batch_queries_and_keep_version_metadata(self):
        with library.connect(self.path) as db:
            owner = self.users['owner']
            experiment_id = experiments.save_experiment(db, owner, {'title': 'Benchmark'})
            item_ids = []
            for run_number in range(100):
                run_id = experiments.save_run(
                    db, owner, {'experiment_id': experiment_id, 'title': f'Run {run_number}'},
                )
                for item_number in range(10):
                    data = {'experiment_id': experiment_id, 'run_id': run_id, 'kind': 'data',
                            'title': f'Item {item_number}', 'filename': 'data.txt'}
                    item = experiments.save_item(db, owner, data, b'original')
                    if run_number in (0, 99) and item_number == 0:
                        experiments.save_item(db, owner, dict(data, id=item, revision=1), b'updated')
                    item_ids.append(item)

            queries = []
            db.set_trace_callback(queries.append)
            try:
                listing = experiments.visible_experiments(db, owner)
                self.assertLessEqual(len(queries), 2)
                queries.clear()
                detail = experiments.detail(db, owner, experiment_id)
                self.assertLessEqual(len(queries), 10)
            finally:
                db.set_trace_callback(None)

            self.assertEqual(listing, [detail['experiment']])
            self.assertEqual([i['id'] for i in detail['items']], item_ids[::-1])
            for item in [detail['items'][9], detail['items'][-1]]:
                self.assertEqual([v['number'] for v in item['versions']], [2, 1])
                self.assertEqual([v['size'] for v in item['versions']], [7, 8])
                self.assertTrue(all('content' not in v and 'item_id' not in v for v in item['versions']))

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
