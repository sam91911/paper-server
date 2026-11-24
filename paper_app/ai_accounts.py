"""Invitation-based enrollment and Ed25519 sign-in for AI accounts."""

import secrets
import time

from . import accounts, database as storage, key_auth

REGISTRATION_PREFIX = "/api/ai/register/"
INVITE_SECONDS = 900
ACCESS_SECONDS = 900

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
"""


def create_invite(db, data):
    username = accounts.identity(data.get("username"))
    role = data.get("role")
    if role not in ("local", "cloud"):
        raise ValueError("Choose local or cloud for the AI account.")
    if db.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone():
        raise ValueError("That username is already in use.")
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM ai_invites WHERE expires<=?", (now,))
    db.execute("INSERT INTO ai_invites VALUES (?,?,?,?)", (accounts.token_hash(token), username, role, now + INVITE_SECONDS))
    return {"registration_path": REGISTRATION_PREFIX + token, "expires_in": INVITE_SECONDS,
            "username": username, "role": role}


def register(db, token, data):
    message = "This AI registration URL is invalid, expired, or already used."
    if not accounts.valid_token(token):
        raise ValueError(message)
    invite = db.execute(
        "DELETE FROM ai_invites WHERE token_hash=? AND expires>? RETURNING username,role",
        (accounts.token_hash(token), int(time.time())),
    ).fetchone()
    if not invite:
        raise ValueError(message)
    username, role = invite
    public_key = key_auth.decode_field(data, "public_key", 32)
    key_auth.verify(public_key, data, f"paper-library:register:{username}:{REGISTRATION_PREFIX}{token}")
    try:
        account_id = accounts.create_account(db, username, secrets.token_urlsafe(48), role)
    except storage.INTEGRITY_ERRORS as error:
        raise ValueError("That username is already in use.") from error
    db.execute("INSERT INTO ai_public_keys VALUES (?,?)", (account_id, public_key))
    db.execute("DELETE FROM ai_invites WHERE LOWER(username)=LOWER(?)", (username,))
    return {"account": {"id": account_id, "username": username, "role": role}}


def registered_key(db, username):
    return db.execute(
        "SELECT a.id,a.username,k.public_key FROM ai_public_keys k JOIN accounts a ON a.id=k.account_id "
        "WHERE a.username=? AND a.role='ai'", (username,),
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
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_SECONDS}
