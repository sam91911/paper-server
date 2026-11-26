"""Schedule work for an enrolled agent's locally configured runner."""

import re
import time
from uuid import uuid4

from . import ai_accounts, sharing

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_schedules (
        agent_id INTEGER PRIMARY KEY REFERENCES accounts(id), interval_seconds INTEGER NOT NULL,
        next_run INTEGER, failures INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES agent_schedules(agent_id),
        started INTEGER NOT NULL, deadline INTEGER NOT NULL, finished INTEGER, success BOOLEAN,
        detail TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS agent_runs_history ON agent_runs(agent_id, started DESC, id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_active ON agent_runs(agent_id) WHERE finished IS NULL",
)
RUN_TIMEOUT = 1800


def dashboard(db, account):
    return {"schedules": [
        {"agent": row["username"], "interval_seconds": row["interval_seconds"] or 0,
         "next_run": row["next_run"], "failures": row["failures"] or 0,
         "runs": [dict(run) for run in db.execute(
             """SELECT started, deadline, finished, success, detail FROM agent_runs
                WHERE agent_id=? ORDER BY started DESC,id LIMIT 10""", (row["id"],)
         )]}
        for row in db.execute(
            """SELECT a.id,a.username,s.interval_seconds,s.next_run,s.failures
               FROM ai_operators o JOIN accounts a ON a.id=o.agent_id
               LEFT JOIN agent_schedules s ON s.agent_id=a.id
               WHERE o.operator_id=? AND a.role='ai' AND a.disabled_at IS NULL ORDER BY a.username""",
            (account["id"],),
        )
    ]}


def update(db, account, data):
    now = int(time.time())
    action = data.get("action")
    if account["role"] == "user":
        agent = ai_accounts.managed_agent(db, account, data.get("agent"))
        if agent["disabled_at"] is not None:
            raise LookupError("Agent unavailable.")
        agent_id = agent["id"]
        if action == "configure":
            interval = data.get("interval_seconds")
            if type(interval) is not int or (interval and not 60 <= interval <= 86400):
                raise ValueError("Set an interval of 60–86400 seconds, or 0 to disable recurring runs.")
            db.execute("""INSERT INTO agent_schedules(agent_id,interval_seconds,next_run) VALUES (?,?,?)
                          ON CONFLICT(agent_id) DO UPDATE SET interval_seconds=excluded.interval_seconds,
                          next_run=excluded.next_run""", (agent_id, interval, now + interval if interval else None))
        elif action == "run_now":
            db.execute("""INSERT INTO agent_schedules(agent_id,interval_seconds,next_run) VALUES (?,0,?)
                          ON CONFLICT(agent_id) DO UPDATE SET next_run=excluded.next_run""", (agent_id, now))
        else:
            raise ValueError("Choose a schedule action.")
        return dashboard(db, account)

    if account["role"] not in ("local", "cloud"):
        raise sharing.AccessDenied
    agent_id = account["id"]
    if action == "claim":
        expired = db.execute("""UPDATE agent_runs SET finished=?,success=FALSE,detail='Runner did not report completion.'
                                WHERE agent_id=? AND finished IS NULL AND deadline<=? RETURNING id""",
                             (now, agent_id, now)).fetchone()
        if expired:
            db.execute("UPDATE agent_schedules SET failures=failures+1 WHERE agent_id=?", (agent_id,))
        schedule = db.execute("""SELECT interval_seconds FROM agent_schedules s WHERE agent_id=? AND next_run<=?
                                 AND NOT EXISTS (SELECT 1 FROM agent_runs r WHERE r.agent_id=s.agent_id
                                                 AND r.finished IS NULL)""", (agent_id, now)).fetchone()
        if schedule is None:
            return {"run": None}
        run_id = uuid4().hex
        db.execute("INSERT INTO agent_runs(id,agent_id,started,deadline) VALUES (?,?,?,?)",
                   (run_id, agent_id, now, now + RUN_TIMEOUT))
        interval = schedule["interval_seconds"]
        db.execute("UPDATE agent_schedules SET next_run=? WHERE agent_id=?",
                   (now + interval if interval else None, agent_id))
        return {"run": {"id": run_id, "timeout_seconds": RUN_TIMEOUT}}
    if action == "finish":
        run_id, success, detail = data.get("id"), data.get("success"), data.get("detail", "")
        if (not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id)
                or type(success) is not bool or not isinstance(detail, str) or len(detail) > 500 or "\x00" in detail):
            raise ValueError("Provide a run ID, outcome, and a summary of up to 500 characters.")
        run = db.execute("SELECT finished,success,detail FROM agent_runs WHERE id=? AND agent_id=?",
                         (run_id, agent_id)).fetchone()
        if run is None:
            raise LookupError("Run unavailable.")
        if run["finished"] is not None:
            if run["success"] == success and run["detail"] == detail:
                return {}
            raise sharing.EditConflict("This run already has an outcome.")
        db.execute("UPDATE agent_runs SET finished=?,success=?,detail=? WHERE id=?", (now, success, detail, run_id))
        db.execute("UPDATE agent_schedules SET failures=CASE WHEN ? THEN 0 ELSE failures+1 END WHERE agent_id=?",
                   (success, agent_id))
        return {}
    raise ValueError("Choose a runner action.")
