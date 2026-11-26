import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_app import accounts, ai_accounts, library
from paper_client import agent
from test_skill_api import request


class AgentScheduleTests(unittest.TestCase):
    def test_runner_claim_history_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "library.sqlite3"
            library.initialize(database)
            with library.connect(database) as db:
                owner = accounts.create_account(db, "owner", "test password", "user")
                worker = accounts.create_account(db, "worker", "test password", "local")
                other = accounts.create_account(db, "other", "test password", "user")
                ai_accounts.assign_operator(db, "worker", "owner")
                owner_key = accounts.create_key(db, owner, "owner")
                worker_key = accounts.create_key(db, worker, "worker")
                other_key = accounts.create_key(db, other, "other")

            def update(key, action, **data):
                return request(database, "/api/agent-schedules", key=key, data={"action": action, **data})

            class Client:
                def request(self, route, data):
                    status, result = request(database, route, key=worker_key, data=data)
                    if status != 200:
                        raise AssertionError(result)
                    return json.dumps(result)

            with patch("paper_app.agent_schedules.time.time", return_value=100):
                self.assertEqual(update(other_key, "run_now", agent="worker")[0], 404)
                self.assertEqual(update(owner_key, "configure", agent="worker", interval_seconds=60)[0], 200)
                self.assertIsNone(update(worker_key, "claim")[1]["run"])
                self.assertEqual(update(owner_key, "run_now", agent="worker")[0], 200)
                agent.run_schedule(Client(), Path(directory) / "identity.json",
                                   [sys.executable, "-c", "import os; assert os.environ['PAPER_AGENT_RUN_ID']"], once=True)
                _, result = request(database, "/api/agent-schedules", key=owner_key)
                self.assertTrue(result["schedules"][0]["runs"][0]["success"])
            with patch("paper_app.agent_schedules.time.time", return_value=160):
                active = update(worker_key, "claim")[1]["run"]
                self.assertIsNone(update(worker_key, "claim")[1]["run"])
            with patch("paper_app.agent_schedules.time.time", return_value=160 + active["timeout_seconds"]):
                next_run = update(worker_key, "claim")[1]["run"]
                self.assertNotEqual(next_run["id"], active["id"])
                self.assertEqual(update(worker_key, "finish", id=active["id"], success=True)[0], 409)
                _, result = request(database, "/api/agent-schedules", key=owner_key)
                self.assertEqual(result["schedules"][0]["failures"], 1)
                finish = {"id": next_run["id"], "success": True}
                self.assertEqual(update(worker_key, "finish", **finish)[0], 200)
                self.assertEqual(update(worker_key, "finish", **finish)[0], 200)
                _, result = request(database, "/api/agent-schedules", key=owner_key)
                self.assertEqual(result["schedules"][0]["failures"], 0)
