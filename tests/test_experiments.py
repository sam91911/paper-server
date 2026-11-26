import json
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from unittest.mock import Mock

from paper_app import accounts, ai_accounts, experiments, library, sharing
from paper_client import agent
from test_skill_api import request


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

    def test_compute_tasks_have_resource_estimates_and_one_claimant(self):
        with library.connect(self.path) as db:
            owner = self.users["owner"]
            keys = {name: accounts.create_key(db, user["id"], "Compute")
                    for name, user in self.users.items()}
            experiment = experiments.save_experiment(db, owner, {"title": "Compute benchmark", "audience": "owner"})
            experiments.set_grants(db, "experiment", experiment, owner,
                                   experiments.require_experiment(db, experiment, owner), ["local", "cloud"], [])
        route = "/api/experiment-compute"
        query = f"{route}?experiment_id={experiment}"
        estimate = {"cpu_cores": 32, "ram_gib": 128, "disk_gib": 512, "wall_minutes": 240,
                    "gpu_count": 2, "vram_gib_per_gpu": 48}
        create = {"action": "create", "experiment_id": experiment, "title": "Rerun the benchmark",
                  "instructions": "Run the pinned benchmark in a dedicated VM.", "resources": estimate}
        self.assertEqual(request(self.path, route, key=keys["owner"], data={**create, "resources": {}})[0], 400)
        self.assertEqual(request(self.path, route, key=keys["local"], data=create)[0], 403)
        status, task = request(self.path, route, key=keys["owner"], data=create)
        self.assertEqual(status, 200)
        self.assertEqual(request(self.path, query, key=keys["human"])[0], 404)
        self.assertEqual(request(self.path, query, key=keys["local"])[1]["tasks"][0]["resources"], estimate)
        claim = {"action": "claim", "experiment_id": experiment, "id": task["id"], "revision": task["revision"]}

        def compete(name):
            return name, request(self.path, route, key=keys[name], data=claim)[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = dict(pool.map(compete, ("local", "cloud")))
        self.assertEqual(sorted(claims.values()), [200, 409])
        winner = next(name for name, status in claims.items() if status == 200)
        loser = next(name for name, status in claims.items() if status == 409)
        result = {**claim, "action": "complete", "revision": 2, "result": "Completed in 190 minutes."}
        self.assertEqual(request(self.path, route, key=keys[loser], data=result)[0], 403)
        self.assertEqual(request(self.path, route, key=keys[winner], data=result)[0], 200)
        saved = request(self.path, query, key=keys["owner"])[1]["tasks"][0]
        self.assertEqual((saved["status"], saved["claimant"], saved["result"]),
                         ("complete", winner, result["result"]))
        status, second = request(self.path, route, key=keys["owner"], data=create)
        self.assertEqual(status, 200)
        claim["id"] = second["id"]
        self.assertEqual(request(self.path, route, key=keys["local"], data=claim)[0], 200)
        release = {**claim, "action": "release", "revision": 2}
        self.assertEqual(request(self.path, route, key=keys["local"], data=release)[0], 200)
        self.assertEqual(request(self.path, route, key=keys["cloud"], data={**claim, "revision": 3})[0], 200)

    def test_rerun_checks_follow_run_visibility_and_revision(self):
        with library.connect(self.path) as db:
            owner, reviewer, outsider, agent = (self.users[name] for name in ('owner', 'editor', 'human', 'local'))
            owner_key, reviewer_key, outsider_key, agent_key = (
                accounts.create_key(db, user['id'], 'Test') for user in (owner, reviewer, outsider, agent)
            )
            experiment = experiments.save_experiment(db, owner, {'title': 'Experiment', 'audience': 'all'})
            experiments.set_grants(db, 'experiment', experiment, owner,
                                   experiments.require_experiment(db, experiment, owner), ['editor'], [])

        record = {'dependencies': ['Python 3.12'], 'inputs': [{'name': 'input.csv', 'sha256': 'A' * 64}],
                  'seed': '42', 'expected_output': 'Score equals 0.8'}
        run_data = {'experiment_id': experiment, 'title': 'Original run', 'status': 'complete', 'reproduction': record}
        status, saved = request(self.path, '/api/experiment-runs', key=owner_key, data=run_data)
        self.assertEqual(status, 200, saved)
        run = saved['id']
        grant = {'kind': 'run', 'id': run, 'readers': ['editor', 'local']}
        self.assertEqual(request(self.path, '/api/research-grants', key=owner_key, data=grant)[0], 200)
        detail = f'/api/experiment-detail?id={experiment}'
        visible = request(self.path, detail, key=reviewer_key)[1]['runs'][0]
        record['inputs'][0]['sha256'] = 'a' * 64
        self.assertEqual(visible['reproduction'], record)
        self.assertFalse(visible['can_edit'])
        self.assertTrue(visible['can_verify'])
        self.assertEqual(request(self.path, detail, key=outsider_key)[1]['runs'], [])
        endpoint = '/api/run-reproductions'
        check = {'run_id': run, 'run_revision': 1, 'outcome': 'matched', 'observed': 'Rerun scored 0.8.'}
        for key in (owner_key, agent_key, outsider_key):
            self.assertEqual(request(self.path, endpoint, key=key, data=check)[0], 403)
        self.assertEqual(request(self.path, endpoint, key=reviewer_key, data=dict(check, observed=''))[0], 400)
        self.assertEqual(request(self.path, endpoint, key=reviewer_key, data=check)[0], 200)
        self.assertEqual(request(self.path, endpoint, key=reviewer_key, data=dict(check, observed='Exact match.'))[0], 200)

        run_data.pop('reproduction')
        self.assertEqual(request(self.path, '/api/experiment-runs', key=owner_key,
                                 data=dict(run_data, id=run, revision=1))[0], 200)
        self.assertEqual(request(self.path, endpoint, key=reviewer_key, data=check)[0], 409)
        later = request(self.path, detail, key=reviewer_key)[1]['runs'][0]
        self.assertEqual(later['reproduction'], record)
        self.assertEqual(later['revision'], 2)
        self.assertEqual([(r['run_revision'], r['reviewer'], r['mine'], r['observed'])
                          for r in later['reproduction_checks']], [(1, 'editor', True, 'Exact match.')])
        self.assertEqual(request(self.path, '/api/research-grants', key=owner_key, data=dict(grant, readers=[]))[0], 200)
        self.assertEqual(request(self.path, detail, key=reviewer_key)[1]['runs'], [])

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

    def test_upload_git_snapshot_and_browse_committed_files(self):
        repository = self.path.with_name("repo")
        repository.mkdir()
        git = ["git", "-C", str(repository)]
        subprocess.run([*git, "init", "-q"], check=True)
        (repository / "src").mkdir()
        source = repository / "src" / "model.py"
        source.write_text("print('committed model')\n")
        subprocess.run([*git, "add", "src"], check=True)
        subprocess.run([*git, "-c", "user.name=Test", "-c", "user.email=test@example.org",
                        "-c", "commit.gpgsign=false", "commit", "-qm", "Add test model"], check=True)
        commit = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        source.write_text("uncommitted change\n")
        (repository / "local.txt").write_text("untracked file")
        with library.connect(self.path) as db:
            owner, other = self.users["cloud"], self.users["human"]
            key = accounts.create_key(db, owner["id"], "experiment owner")
            other_key = accounts.create_key(db, other["id"], "other reader")
            experiment = experiments.save_experiment(db, owner, {"title": "Test experiment"})
            run = experiments.save_run(db, owner, {"experiment_id": experiment, "title": "Run"})

        def submit(metadata, payload):
            status, response = request(self.path, "/api/research-upload", key=key, binary=payload, headers={
                "Content-Type": "application/octet-stream",
                "X-Research-Metadata": quote(json.dumps(metadata), safe=""),
            })
            self.assertEqual(status, 200, response)
            return response

        client = Mock()
        client.upload_artifact.side_effect = submit
        args = SimpleNamespace(experiment_id=experiment, run_id=run, title="Source", description="Reproduction source",
                               audience="owner", repository=repository, commit="HEAD", kind=None, file=None,
                               item_id=None, item_revision=None)
        snapshot = agent.upload_artifact(client, args)
        route = f"/research-versions/{snapshot['version_id']}"
        self.assertEqual(request(self.path, route + "/entries", key=key), (200, {
            "commit": commit, "files": [{"path": "src/model.py", "size": len(b"print('committed model')\n")}],
        }))
        self.assertEqual(request(self.path, route + "/entry?path=src%2Fmodel.py", key=key),
                         (200, b"print('committed model')\n"))
        self.assertEqual(request(self.path, route + "/entry?path=local.txt", key=key)[0], 404)
        self.assertEqual(request(self.path, route + "/entries", key=other_key)[0], 404)
        self.assertEqual(request(self.path, route + "/entry?path=src%2Fmodel.py", key=other_key)[0], 404)

        results = repository / "results.csv"
        results.write_text("score\n1.0\n")
        output = agent.upload_artifact(client, SimpleNamespace(
            **{**vars(args), "repository": None, "file": results, "title": "Results"},
        ))
        self.assertEqual(request(self.path, f"/research-versions/{output['version_id']}/file", key=key),
                         (200, b"score\n1.0\n"))

    def test_operator_manages_agent_owned_experiment_runs_and_artifacts(self):
        with library.connect(self.path) as db:
            operator, agent, outsider = (self.users[name] for name in ('owner', 'cloud', 'human'))
            ai_accounts.assign_operator(db, agent['username'], operator['username'])
            experiment = experiments.save_experiment(db, agent, {'title': 'Private experiment'})
            run = experiments.save_run(db, agent, {'experiment_id': experiment, 'title': 'Private run'})
            data = {'experiment_id': experiment, 'run_id': run, 'title': 'Private artifact', 'kind': 'data', 'filename': 'a.csv'}
            item = experiments.save_item(db, agent, data, b'first')
            self.assertEqual(experiments.visible_experiments(db, outsider), [])
            self.assertEqual([row['id'] for row in experiments.visible_experiments(db, operator)], [experiment])
            detail = experiments.detail(db, operator, experiment)
            self.assertTrue(detail['can_edit'])
            self.assertTrue(detail['runs'][0]['can_edit'])
            self.assertEqual(detail['items'][0]['id'], item)
            self.assertEqual(experiments.version_content(db, operator, detail['items'][0]['versions'][0]['id'])[1], b'first')
            experiments.save_experiment(db, operator, {'id': experiment, 'title': 'Edited experiment', 'revision': 1})
            experiments.save_run(db, operator, {'id': run, 'experiment_id': experiment, 'title': 'Edited run', 'revision': 1})
            experiments.save_item(db, operator, dict(data, id=item, revision=1), b'second')
            row = experiments.require_item(db, item, operator, edit=True)
            self.assertEqual(row['owner_id'], agent['id'])
            experiments.set_grants(db, 'item', item, operator, row, [outsider['username']], [])
            self.assertEqual(experiments.detail(db, operator, experiment)['items'][0]['readers'], [outsider['username']])
            with self.assertRaises(sharing.AccessDenied):
                experiments.require_item(db, item, outsider)

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
