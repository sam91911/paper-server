"""Invitation-based enrollment and Ed25519 sign-in for AI accounts."""

import re
import secrets
import time

from . import accounts, database as storage, key_auth, sharing

REGISTRATION_PREFIX = "/api/ai/register/"
INVITE_SECONDS = 900
ACCESS_SECONDS = 900
HEARTBEAT_SECONDS = 60
ONLINE_SECONDS = 3 * HEARTBEAT_SECONDS
HEARTBEAT_COALESCE_SECONDS = 15
PAGE_SIZE = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_invites (
    token_hash BLOB PRIMARY KEY, username TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('local', 'cloud')), expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_public_keys (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
    public_key BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_challenges (
    token_hash BLOB PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES ai_public_keys(account_id) ON DELETE CASCADE,
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_operators (
    agent_id INTEGER PRIMARY KEY REFERENCES accounts(id),
    operator_id INTEGER NOT NULL REFERENCES accounts(id)
);
CREATE TABLE IF NOT EXISTS ai_goal_delegates (
    agent_id INTEGER NOT NULL REFERENCES ai_operators(agent_id),
    delegate_id INTEGER NOT NULL REFERENCES accounts(id),
    PRIMARY KEY (agent_id, delegate_id)
);
CREATE INDEX IF NOT EXISTS ai_goal_delegates_account ON ai_goal_delegates(delegate_id, agent_id);
"""


def initialize(db):
    for table, columns in (
        ("ai_invites", (("invite_id", "TEXT"), ("issuer_id", "INTEGER REFERENCES accounts(id)"),
                        ("rotate_id", "INTEGER REFERENCES accounts(id)"), ("created", "INTEGER"),
                        ("used_at", "INTEGER"), ("canceled_at", "INTEGER"))),
        ("ai_public_keys", (("last_authenticated", "INTEGER"),)),
    ):
        existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns:
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ai_invites_identity ON ai_invites(invite_id)")
    db.execute("CREATE INDEX IF NOT EXISTS ai_invites_issuer ON ai_invites(issuer_id, created)")


STATUS = """CASE WHEN used_at IS NOT NULL THEN 'used' WHEN canceled_at IS NOT NULL THEN 'canceled'
                 WHEN expires<=? THEN 'expired' ELSE 'pending' END"""
ACCOUNT_FIELDS = f"a.id,a.username,{accounts.ROLE_SQL.format(alias='a')} AS role"


def find_account(db, username):
    return db.execute(f"SELECT {ACCOUNT_FIELDS},a.disabled_at FROM accounts a WHERE a.username=?",
                      (accounts.identity(username),)).fetchone()


def assign_operator(db, username, operator):
    agent, owner = find_account(db, username), find_account(db, operator)
    if not agent or agent["role"] not in ("local", "cloud") or not owner or owner["role"] != "user":
        raise ValueError("Choose an AI account and a trusted human operator.")
    db.execute(
        "DELETE FROM ai_goal_delegates WHERE agent_id IN (SELECT agent_id FROM ai_operators WHERE agent_id=? AND operator_id<>?)",
        (agent["id"], owner["id"]),
    )
    db.execute("INSERT INTO ai_operators VALUES (?,?) ON CONFLICT (agent_id) DO UPDATE SET operator_id=excluded.operator_id",
               (agent["id"], owner["id"]))
    now = int(time.time())
    db.execute("UPDATE ai_invites SET canceled_at=? WHERE rotate_id=? AND issuer_id<>? AND used_at IS NULL "
               "AND canceled_at IS NULL AND expires>?", (now, agent["id"], owner["id"], now))


def invitation_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Choose an AI invitation.")
    return value


def managed_agent(db, operator, username):
    agent = find_account(db, username)
    if not agent or agent["role"] not in ("local", "cloud") or not db.execute(
        "SELECT 1 FROM ai_operators WHERE agent_id=? AND operator_id=?", (agent["id"], operator["id"]),
    ).fetchone():
        raise LookupError("AI account unavailable.")
    return agent


def assignable_goal_agents(db, account):
    if account["role"] not in ("user", "member"):
        return []
    return db.execute(
        f"SELECT {ACCOUNT_FIELDS},a.disabled_at FROM ai_operators o JOIN accounts a ON a.id=o.agent_id "
        "JOIN accounts owner ON owner.id=o.operator_id "
        "LEFT JOIN ai_goal_delegates d ON d.agent_id=a.id AND d.delegate_id=? "
        "WHERE a.role='ai' AND owner.role='user' AND owner.trusted=1 AND owner.disabled_at IS NULL "
        "AND (o.operator_id=? OR d.delegate_id IS NOT NULL) ORDER BY a.username",
        (account["id"], account["id"]),
    ).fetchall()


def update_goal_delegate(db, operator, data):
    action = data.get("action")
    if action not in ("grant", "revoke"):
        raise ValueError("Choose grant or revoke.")
    agent = managed_agent(db, operator, data.get("agent"))
    delegate = find_account(db, data.get("username"))
    if not delegate or delegate["role"] not in ("user", "member") or delegate["id"] == operator["id"]:
        raise ValueError("Choose another human account.")
    ids = (agent["id"], delegate["id"])
    if action == "grant":
        if agent["disabled_at"] is not None or delegate["disabled_at"] is not None:
            raise ValueError("Choose an active agent and human account.")
        db.execute("INSERT INTO ai_goal_delegates(agent_id,delegate_id) VALUES (?,?) ON CONFLICT DO NOTHING", ids)
    else:
        db.execute("DELETE FROM ai_goal_delegates WHERE agent_id=? AND delegate_id=?", ids)


def deactivate(db, operator, username):
    agent = managed_agent(db, operator, username)
    now = int(time.time())
    disabled = agent["disabled_at"] if agent["disabled_at"] is not None else now
    db.execute("UPDATE accounts SET disabled_at=? WHERE id=?", (disabled, agent["id"]))
    revoke_credentials(db, agent["id"])
    db.execute("UPDATE ai_invites SET canceled_at=? WHERE rotate_id=? AND used_at IS NULL "
               "AND canceled_at IS NULL AND expires>?", (now, agent["id"], now))
    return {"username": agent["username"], "disabled_at": disabled}


def recent_heartbeat(db, account, now):
    if account["role"] not in ("local", "cloud"):
        raise sharing.AccessDenied
    last = db.execute("SELECT last_heartbeat FROM accounts WHERE id=?", (account["id"],)).fetchone()[0]
    if last is not None and 0 <= now - last < HEARTBEAT_COALESCE_SECONDS:
        return {"last_heartbeat": last, "interval_seconds": HEARTBEAT_SECONDS}
    return None


def heartbeat(db, account):
    now = int(time.time())
    recent = recent_heartbeat(db, account, now)
    if recent is not None:
        return recent
    db.execute("UPDATE accounts SET last_heartbeat=? WHERE id=?", (now, account["id"]))
    return {"last_heartbeat": now, "interval_seconds": HEARTBEAT_SECONDS}


def dashboard(db, operator, before=None):
    now = int(time.time())
    cursor_clause, values = "", (now, operator["id"])
    if before is not None:
        cursor = db.execute("SELECT created,invite_id FROM ai_invites WHERE invite_id=? AND issuer_id=?",
                            (invitation_id(before), operator["id"])).fetchone()
        if cursor is None:
            raise LookupError("AI invitation unavailable.")
        cursor_clause = "AND (created<? OR (created=? AND invite_id<?))"
        values += (cursor["created"], cursor["created"], cursor["invite_id"])
    invitations = [dict(row) for row in db.execute(
        f"SELECT invite_id,username,role,created,expires,{STATUS} AS status,"
        "CASE WHEN rotate_id IS NULL THEN 'enroll' ELSE 'rotate' END AS mode "
        f"FROM ai_invites WHERE issuer_id=? {cursor_clause} ORDER BY created DESC,invite_id DESC LIMIT ?",
        (*values, PAGE_SIZE + 1),
    )]
    agents = [dict(row) for row in db.execute(
        f"SELECT {ACCOUNT_FIELDS},a.disabled_at,a.last_heartbeat,k.last_authenticated "
        "FROM ai_operators o JOIN accounts a ON a.id=o.agent_id "
        "LEFT JOIN ai_public_keys k ON k.account_id=a.id WHERE o.operator_id=? AND a.role='ai' ORDER BY a.username",
        (operator["id"],),
    )]
    delegates = {}
    for row in db.execute(
        "SELECT d.agent_id,a.username FROM ai_goal_delegates d JOIN accounts a ON a.id=d.delegate_id "
        "JOIN ai_operators o ON o.agent_id=d.agent_id WHERE o.operator_id=? ORDER BY a.username", (operator["id"],),
    ):
        delegates.setdefault(row["agent_id"], []).append(row["username"])
    for agent in agents:
        agent["goal_delegates"] = delegates.get(agent["id"], [])
        last = agent["last_heartbeat"]
        agent["online"] = agent["disabled_at"] is None and last is not None and last > now - ONLINE_SECONDS
    return {"invitations": invitations[:PAGE_SIZE], "agents": agents,
            "next_before": invitations[PAGE_SIZE - 1]["invite_id"] if len(invitations) > PAGE_SIZE else None}


def manage_invite(db, operator, data):
    action = data.get("action", "create")
    now = int(time.time())
    if action in ("cancel", "replace"):
        invite_id = invitation_id(data.get("invite_id"))
        row = db.execute(f"SELECT username,role,rotate_id,{STATUS} AS status FROM ai_invites "
                         "WHERE invite_id=? AND issuer_id=?", (now, invite_id, operator["id"])).fetchone()
        if not row:
            raise LookupError("AI invitation unavailable.")
        if row["status"] == "pending":
            db.execute("UPDATE ai_invites SET canceled_at=? WHERE invite_id=?", (now, invite_id))
        if action == "cancel":
            if row["status"] not in ("pending", "canceled"):
                raise ValueError("Only pending invitations can be canceled.")
            return {"invite_id": invite_id, "status": "canceled"}
        if row["status"] == "used":
            raise ValueError("This invitation was used. Rotate the agent's key to enroll a replacement.")
        data = dict(row)
        action = "rotate" if row["rotate_id"] is not None else "create"
    if action == "rotate":
        agent = managed_agent(db, operator, data.get("username"))
        if agent["disabled_at"] is not None or (data.get("rotate_id") is not None and data["rotate_id"] != agent["id"]):
            raise LookupError("AI account unavailable.")
        return issue_invite(db, operator, agent["username"], agent["role"], now, agent["id"])
    if action != "create":
        raise ValueError("Choose create, rotate, cancel, or replace.")
    username = accounts.identity(data.get("username"))
    role = data.get("role")
    if role not in ("local", "cloud"):
        raise ValueError("Choose local or cloud for the AI account.")
    if db.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone():
        raise ValueError("That username is already in use.")
    return issue_invite(db, operator, username, role, now)


def issue_invite(db, operator, username, role, now, rotate_id=None):
    token, invite_id = secrets.token_urlsafe(32), secrets.token_hex(16)
    db.execute("UPDATE ai_invites SET canceled_at=? WHERE issuer_id=? AND LOWER(username)=LOWER(?) "
               "AND used_at IS NULL AND canceled_at IS NULL AND expires>?", (now, operator["id"], username, now))
    db.execute("INSERT INTO ai_invites(token_hash,username,role,expires,invite_id,issuer_id,rotate_id,created) "
               "VALUES (?,?,?,?,?,?,?,?)",
               (accounts.token_hash(token), username, role, now + INVITE_SECONDS, invite_id, operator["id"], rotate_id, now))
    return {"registration_path": REGISTRATION_PREFIX + token, "expires_in": INVITE_SECONDS,
            "username": username, "role": role, "invite_id": invite_id, "mode": "rotate" if rotate_id else "enroll"}


def register(db, token, data):
    message = "This AI registration URL is invalid, expired, or already used."
    if not accounts.valid_token(token):
        raise ValueError(message)
    now = int(time.time())
    invite = db.execute(
        "UPDATE ai_invites SET used_at=? WHERE token_hash=? AND expires>? AND used_at IS NULL AND canceled_at IS NULL "
        "RETURNING username,role,issuer_id,rotate_id",
        (now, accounts.token_hash(token), now),
    ).fetchone()
    if not invite:
        raise ValueError(message)
    username, role, issuer_id, rotate_id = invite
    public_key = key_auth.decode_field(data, "public_key", 32)
    key_auth.verify(public_key, data, f"paper-library:register:{username}:{REGISTRATION_PREFIX}{token}")
    if issuer_id is not None and not db.execute("SELECT 1 FROM accounts WHERE id=? AND role='user' AND trusted=1",
                                               (issuer_id,)).fetchone():
        raise ValueError(message)
    if rotate_id is not None:
        agent = find_account(db, username)
        if not agent or agent["disabled_at"] is not None or (agent["id"], agent["role"]) != (rotate_id, role) or not db.execute(
            "SELECT 1 FROM ai_operators WHERE agent_id=? AND operator_id=?", (rotate_id, issuer_id),
        ).fetchone():
            raise ValueError(message)
        rotate_key(db, rotate_id, public_key)
        return {"account": {"id": rotate_id, "username": username, "role": role}}
    try:
        account_id = accounts.create_account(db, username, secrets.token_urlsafe(48), role)
    except storage.INTEGRITY_ERRORS as error:
        raise ValueError("That username is already in use.") from error
    db.execute("INSERT INTO ai_public_keys(account_id,public_key) VALUES (?,?)", (account_id, public_key))
    if issuer_id is not None:
        db.execute("INSERT INTO ai_operators VALUES (?,?)", (account_id, issuer_id))
    db.execute("UPDATE ai_invites SET canceled_at=? WHERE LOWER(username)=LOWER(?) "
               "AND used_at IS NULL AND canceled_at IS NULL AND expires>?", (now, username, now))
    return {"account": {"id": account_id, "username": username, "role": role}}


def rotate_key(db, account_id, public_key):
    if db.execute("SELECT 1 FROM ai_public_keys WHERE account_id=? AND public_key=?",
                  (account_id, public_key)).fetchone():
        raise ValueError("Generate a new private key for this rotation.")
    db.execute("INSERT INTO ai_public_keys(account_id,public_key) VALUES (?,?) "
               "ON CONFLICT (account_id) DO UPDATE SET public_key=excluded.public_key", (account_id, public_key))
    db.execute("UPDATE accounts SET last_heartbeat=NULL WHERE id=?", (account_id,))
    revoke_credentials(db, account_id)


def revoke_credentials(db, account_id):
    for table in ("sessions", "ai_challenges", "application_keys"):
        db.execute(f"DELETE FROM {table} WHERE account_id=?", (account_id,))


def registered_key(db, username):
    return db.execute(
        "SELECT a.id,a.username,k.public_key FROM ai_public_keys k JOIN accounts a ON a.id=k.account_id "
        "WHERE a.username=? AND a.role='ai' AND a.disabled_at IS NULL", (username,),
    ).fetchone()


def challenge(db, data):
    username = accounts.identity(data.get("username"))
    account = registered_key(db, username)
    if not account:
        raise accounts.SignInRequired
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM ai_challenges WHERE expires<=?", (now,))
    db.execute("INSERT INTO ai_challenges VALUES (?,?,?)",
               (accounts.token_hash(token), account["id"], now + key_auth.CHALLENGE_SECONDS))
    return {"challenge": token, "username": account["username"], "expires_in": key_auth.CHALLENGE_SECONDS}


def login(db, data):
    username = accounts.identity(data.get("username"))
    token = data.get("challenge")
    if not accounts.valid_token(token):
        raise accounts.SignInRequired
    account = registered_key(db, username)
    now = int(time.time())
    if not account or not db.execute(
        "DELETE FROM ai_challenges WHERE token_hash=? AND account_id=? AND expires>?",
        (accounts.token_hash(token), account["id"], now),
    ).rowcount:
        raise accounts.SignInRequired
    key_auth.verify(account["public_key"], data, f"paper-library:login:{account['username']}:{token}")
    access = accounts.start_session(db, account["id"], None, prefix=accounts.AI_SESSION_PREFIX, expires_in=ACCESS_SECONDS)
    db.execute("UPDATE ai_public_keys SET last_authenticated=? WHERE account_id=?", (now, account["id"]))
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_SECONDS}
