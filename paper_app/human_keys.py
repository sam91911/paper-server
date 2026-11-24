"""Browser sessions established with a human account's Ed25519 key."""

import secrets
import time

from . import accounts, database as storage, key_auth

SCHEMA = """
CREATE TABLE IF NOT EXISTS human_public_keys (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id), public_key BLOB NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS human_key_challenges (
    token_hash BLOB PRIMARY KEY, username TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('register', 'login', 'attach')), expires INTEGER NOT NULL
);
"""


def account_key(db, username):
    return db.execute(
        "SELECT a.id,a.username,k.public_key FROM accounts a "
        "JOIN human_public_keys k ON k.account_id=a.id WHERE a.username=? AND a.role='user'",
        (username,),
    ).fetchone()


def message(origin, action, username, nonce):
    return f"paper-library:human:{action}:{origin}:{username}:{nonce}"


def challenge(db, origin, data, account):
    action = data.get("action")
    if action not in ("register", "login", "attach"):
        raise ValueError("Choose register, login, or attach.")
    if action == "attach":
        username = account["username"]
    else:
        username = accounts.identity(data.get("username"))
    if action == "login":
        registered = account_key(db, username)
        if not registered:
            raise accounts.SignInRequired
        username = registered["username"]
    nonce = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM human_key_challenges WHERE expires<=?", (now,))
    db.execute("INSERT INTO human_key_challenges VALUES (?,?,?,?)",
               (accounts.token_hash(f"{origin}:{nonce}"), username, action, now + key_auth.CHALLENGE_SECONDS))
    return {"challenge": nonce, "message": message(origin, action, username, nonce),
            "expires_in": key_auth.CHALLENGE_SECONDS}


def finish(db, origin, action, data, account):
    nonce = data.get("challenge")
    if not accounts.valid_token(nonce):
        raise accounts.SignInRequired
    pending = db.execute(
        "DELETE FROM human_key_challenges WHERE token_hash=? AND action=? AND expires>? RETURNING username",
        (accounts.token_hash(f"{origin}:{nonce}"), action, int(time.time())),
    ).fetchone()
    if not pending:
        raise accounts.SignInRequired
    username = pending["username"]
    if action == "attach" and username != account["username"]:
        raise accounts.SignInRequired
    if action == "login":
        registered = account_key(db, username)
        if not registered:
            raise accounts.SignInRequired
        public_key = registered["public_key"]
    else:
        public_key = key_auth.decode_field(data, "public_key", 32)
    key_auth.verify(public_key, data, message(origin, action, username, nonce))
    if action == "login":
        return registered["id"]
    if action == "register":
        account_id = accounts.register_human(db, {**data, "username": username}, key_only=True)
    else:
        account_id = account["id"]
    try:
        db.execute("INSERT INTO human_public_keys VALUES (?,?)", (account_id, public_key))
    except storage.INTEGRITY_ERRORS as error:
        raise ValueError("This key or account already has a registration.") from error
    return account_id
