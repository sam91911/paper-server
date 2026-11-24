"""Durable, account-scoped goals that connected agents can pursue."""

import hashlib
import json
import re
import time

from . import accounts, experiments, findings, goals, reviews, sharing

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_goals (
        id INTEGER PRIMARY KEY, requester_id INTEGER NOT NULL REFERENCES accounts(id),
        agent_id INTEGER NOT NULL REFERENCES accounts(id),
        agent_role TEXT NOT NULL CHECK (agent_role IN ('local','cloud')),
        objective TEXT NOT NULL, acceptance_criteria TEXT NOT NULL, sources TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('assigned','in_progress','blocked','paused','submitted','completed','canceled')),
        revision INTEGER NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS agent_goal_events (
        goal_id INTEGER NOT NULL REFERENCES agent_goals(id), revision INTEGER NOT NULL,
        actor_id INTEGER NOT NULL REFERENCES accounts(id), request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
        action TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL, evidence TEXT NOT NULL, created INTEGER NOT NULL,
        PRIMARY KEY (goal_id,revision), UNIQUE (actor_id,request_id)
    )""",
    "CREATE INDEX IF NOT EXISTS agent_goals_requester ON agent_goals(requester_id,id)",
    "CREATE INDEX IF NOT EXISTS agent_goals_agent ON agent_goals(agent_id,id)",
)

PAGE_SIZE = 50
HUMAN_ROLES = ("user", "member")
SOURCE_KINDS = ("paper", "document", "thread", "finding", "research_goal", "experiment")
STATES = ("assigned", "in_progress", "blocked", "paused", "submitted", "completed", "canceled")
OWNER_ACTIONS = {
    "pause": (("assigned", "in_progress", "blocked"), "paused"),
    "resume": (("paused",), "assigned"),
    "request_changes": (("submitted",), "in_progress"),
    "accept": (("submitted",), "completed"),
    "cancel": (STATES[:-2], "canceled"),
}
AGENT_ACTIONS = {
    "start": (("assigned", "blocked"), "in_progress"),
    "progress": (("in_progress",), "in_progress"),
    "block": (("in_progress",), "blocked"),
    "submit": (("in_progress",), "submitted"),
}


def text(value, label, maximum, *, required=True):
    if not isinstance(value, str) or "\x00" in value or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"Enter {label} of up to {maximum:,} characters.")
    return value.strip()


def references(data):
    if not isinstance(data, list) or len(data) > 20:
        raise ValueError("Provide up to 20 workspace references.")
    result = {}
    for item in data:
        if not isinstance(item, dict) or item.get("kind") not in SOURCE_KINDS or not reviews.valid_id(item.get("id")):
            raise ValueError("Choose a workspace item type and positive ID.")
        kind, item_id = item["kind"], item["id"]
        result[kind, item_id] = {"kind": kind, "id": item_id}
    return list(result.values())


def check_reference(db, account, item):
    kind, item_id = item["kind"], item["id"]
    if kind == "paper":
        sharing.paper_for(db, item_id, account)
        if db.execute("SELECT 1 FROM archived_papers WHERE paper_id=?", (item_id,)).fetchone():
            raise sharing.AccessDenied
    elif kind in ("document", "thread"):
        target = reviews.target(db, account, kind, item_id, None)
        if kind == "thread":
            return {key: target[key] for key in ("paper_id", "document_id") if target[key] is not None}
    elif kind == "experiment":
        experiments.require_experiment(db, item_id, account)
    else:
        table, require = (("research_findings", findings.require_finding) if kind == "finding" else
                          ("research_goals", goals.require_goal))
        row = db.execute(f"SELECT document_id FROM {table} WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise sharing.AccessDenied
        require(db, account, row["document_id"], item_id)
        return {"document_id": row["document_id"]}
    return {}


def check_references(db, participants, items):
    resolved = []
    for item in items:
        details = {}
        for account in participants:
            details = check_reference(db, account, item)
        resolved.append({**item, **details})
    return resolved


def scoped_rows(db, account, *, goal_id=None, before=None):
    owner = account["role"] in HUMAN_ROLES
    condition = "g.requester_id=?" if owner else "g.agent_id=?"
    parameters = (account["id"],)
    if goal_id is not None:
        condition += " AND g.id=?"
        parameters += (goal_id,)
    if before is not None:
        condition += " AND g.id<?"
        parameters += (before,)
    return db.execute(
        f"""SELECT g.*, h.username AS requester, a.username AS agent,
            {accounts.ROLE_SQL.format(alias='h')} AS requester_role,
            {accounts.ROLE_SQL.format(alias='a')} AS agent_current_role
            FROM agent_goals g JOIN accounts h ON h.id=g.requester_id JOIN accounts a ON a.id=g.agent_id
            WHERE {condition} AND h.role='user' ORDER BY g.id DESC""", parameters,
    )


def participants_for(row):
    return [{"id": row[f"{party}_id"], "username": row[party], "role": row[f"{party}_role"]}
            for party in ("requester", "agent")]


def available_actions(status, owner):
    return [action for action, (allowed, _) in (OWNER_ACTIONS if owner else AGENT_ACTIONS).items() if status in allowed]


def summary(db, account, row):
    owner = account["role"] in HUMAN_ROLES
    source_items = json.loads(row["sources"])
    result = {key: row[key] for key in ("id", "status", "revision", "agent", "agent_role", "requester", "created", "updated")}
    actions = available_actions(row["status"], owner)
    try:
        if row["agent_current_role"] != row["agent_role"]:
            raise sharing.AccessDenied
        source_items = check_references(db, participants_for(row), source_items)
    except (sharing.AccessDenied, LookupError, ValueError):
        if not owner:
            raise LookupError("Agent goal unavailable.") from None
        return {**result, "source_unavailable": True, "actions": [action for action in actions if action in ("pause", "cancel")]}
    return {**result, "objective": row["objective"], "acceptance_criteria": row["acceptance_criteria"],
            "sources": source_items, "source_unavailable": False, "actions": actions}


def read(db, account, *, goal_id=None, before=None):
    if goal_id is None:
        visible = []
        for row in scoped_rows(db, account, before=before):
            try:
                visible.append(summary(db, account, row))
            except LookupError:
                continue
            if len(visible) > PAGE_SIZE:
                break
        return {"goals": visible[:PAGE_SIZE], "next_before": visible[PAGE_SIZE - 1]["id"] if len(visible) > PAGE_SIZE else None}
    row = scoped_rows(db, account, goal_id=goal_id).fetchone()
    if row is None:
        raise LookupError("Agent goal unavailable.")
    goal = summary(db, account, row)
    if goal["source_unavailable"]:
        return {"goal": goal, "events": [], "next_before": None}
    events = []
    limit = before if before is not None else row["revision"] + 1
    for event in db.execute(
        "SELECT e.revision,e.action,e.status,e.note,e.evidence,e.created,a.username AS actor "
        "FROM agent_goal_events e JOIN accounts a ON a.id=e.actor_id WHERE e.goal_id=? AND e.revision<? "
        "ORDER BY e.revision DESC LIMIT ?", (goal_id, limit, PAGE_SIZE + 1),
    ):
        result = dict(event)
        result["evidence"] = json.loads(result["evidence"])
        try:
            result["evidence"] = check_references(db, participants_for(row), result["evidence"])
        except (sharing.AccessDenied, LookupError, ValueError):
            result.update(note="", evidence=[], redacted=True)
        events.append(result)
    return {"goal": goal, "events": events[:PAGE_SIZE],
            "next_before": events[PAGE_SIZE - 1]["revision"] if len(events) > PAGE_SIZE else None}


def create(db, account, data, now):
    if account["role"] not in HUMAN_ROLES:
        raise sharing.AccessDenied
    username = accounts.identity(data.get("agent"))
    agent = db.execute(f"SELECT {reviews.ACCOUNT_FIELDS} FROM accounts a WHERE a.username=?", (username,)).fetchone()
    if not agent or agent["role"] not in reviews.AI_ROLES:
        raise ValueError("Choose a Local AI or Cloud AI account.")
    sources = references(data.get("sources", []))
    try:
        check_references(db, (account, agent), sources)
    except (sharing.AccessDenied, LookupError, ValueError):
        raise ValueError("Share every source and its supporting evidence with the assigned agent first.") from None
    return db.execute(
        """INSERT INTO agent_goals(requester_id,agent_id,agent_role,objective,acceptance_criteria,sources,status,revision,created,updated)
           VALUES (?,?,?,?,?,?,'assigned',1,?,?) RETURNING id""",
        (account["id"], agent["id"], agent["role"], text(data.get("objective"), "an objective", 8000),
         text(data.get("acceptance_criteria"), "acceptance criteria", 8000), json.dumps(sources), now, now),
    ).fetchone()[0]


def update(db, account, data):
    action = data.get("action")
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", request_id):
        raise ValueError("Provide a unique request_id of 16–64 letters, digits, hyphens, or underscores.")
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    previous = db.execute(
        "SELECT goal_id,request_hash FROM agent_goal_events WHERE actor_id=? AND request_id=?", (account["id"], request_id),
    ).fetchone()
    if previous:
        if previous["request_hash"] != digest:
            raise sharing.EditConflict("This request_id was already used with another update.")
        return read(db, account, goal_id=previous["goal_id"])

    now = int(time.time())
    evidence, note = [], ""
    if action == "create":
        goal_id, revision, status = create(db, account, data, now), 1, "assigned"
    else:
        goal_id = data.get("id")
        if not reviews.valid_id(goal_id) or not reviews.valid_id(data.get("revision")) or not isinstance(action, str):
            raise ValueError("Choose an agent goal, revision, and action.")
        row = scoped_rows(db, account, goal_id=goal_id).fetchone()
        if row is None:
            raise LookupError("Agent goal unavailable.")
        current = summary(db, account, row)
        if data["revision"] != row["revision"]:
            raise sharing.EditConflict("This goal changed. Reload it before retrying.")
        if action not in current["actions"]:
            raise sharing.EditConflict("This action is unavailable for the current goal status.")
        owner = account["role"] in HUMAN_ROLES
        _, status = (OWNER_ACTIONS if owner else AGENT_ACTIONS)[action]
        note = text(data.get("note", ""), "a progress note or result", 16000,
                    required=action in ("progress", "block", "submit", "request_changes"))
        evidence = references(data.get("evidence", []))
        try:
            check_references(db, participants_for(row), evidence)
        except (sharing.AccessDenied, LookupError, ValueError):
            raise ValueError("Both participants must be able to read the evidence.") from None
        revision = row["revision"] + 1
        db.execute("UPDATE agent_goals SET status=?,revision=?,updated=? WHERE id=?", (status, revision, now, goal_id))
    db.execute(
        """INSERT INTO agent_goal_events(goal_id,revision,actor_id,request_id,request_hash,action,status,note,evidence,created)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (goal_id, revision, account["id"], request_id, digest, action, status, note, json.dumps(evidence), now),
    )
    return read(db, account, goal_id=goal_id)
