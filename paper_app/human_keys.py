"""Browser sessions established with a human account's Ed25519 key."""

import re
import secrets
import time

from . import accounts, database as storage, key_auth

KEY_TABLE = """CREATE TABLE IF NOT EXISTS human_public_keys (
    key_id TEXT PRIMARY KEY NOT NULL, account_id INTEGER NOT NULL REFERENCES accounts(id),
    public_key BLOB NOT NULL UNIQUE, label TEXT NOT NULL, created INTEGER
)"""
SCHEMA = KEY_TABLE + """;
CREATE TABLE IF NOT EXISTS human_key_challenges (
    token_hash BLOB PRIMARY KEY, username TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('register', 'login', 'attach')), expires INTEGER NOT NULL
);
"""
MAX_KEYS = 8


def initialize(db):
    if "key_id" not in {row["name"] for row in db.execute("PRAGMA table_info(human_public_keys)")}:
        db.execute("ALTER TABLE human_public_keys RENAME TO previous_human_keys")
        db.execute(KEY_TABLE)
        db.execute("INSERT INTO human_public_keys(key_id,account_id,public_key,label) "
                   "SELECT lower(hex(randomblob(16))),account_id,public_key,'Sign-in key' FROM previous_human_keys")
        db.execute("DROP TABLE previous_human_keys")
    db.execute("CREATE INDEX IF NOT EXISTS human_keys_account ON human_public_keys(account_id)")


def account_with_keys(db, username):
    return db.execute(
        "SELECT a.id,a.username FROM accounts a WHERE a.username=? AND a.role='user' "
        "AND EXISTS (SELECT 1 FROM human_public_keys k WHERE k.account_id=a.id)",
        (username,),
    ).fetchone()


def list_keys(db, account_id):
    return [dict(row) for row in db.execute(
        "SELECT key_id,label,created FROM human_public_keys WHERE account_id=? ORDER BY created,key_id",
        (account_id,),
    )]


def revoke(db, account, key_id):
    if not isinstance(key_id, str) or not re.fullmatch(r"[a-f0-9]{32}", key_id):
        raise ValueError("Choose a sign-in key.")
    keys = list_keys(db, account["id"])
    if not any(row["key_id"] == key_id for row in keys):
        raise LookupError("Sign-in key unavailable.")
    if account["key_only"] and len(keys) == 1:
        raise ValueError("Add a backup key before revoking your last sign-in key.")
    db.execute("DELETE FROM human_public_keys WHERE key_id=? AND account_id=?", (key_id, account["id"]))
    db.execute("DELETE FROM sessions WHERE account_id=?", (account["id"],))
    db.execute("DELETE FROM human_key_challenges WHERE username=?", (account["username"],))


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
        registered = account_with_keys(db, username)
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
        registered = account_with_keys(db, username)
        if not registered:
            raise accounts.SignInRequired
        keys = db.execute("SELECT public_key FROM human_public_keys WHERE account_id=?", (registered["id"],))
        sign_in_message = message(origin, action, username, nonce)
        for key in keys:
            try:
                key_auth.verify(key["public_key"], data, sign_in_message)
            except accounts.SignInRequired:
                continue
            return registered["id"]
        raise accounts.SignInRequired
    public_key = key_auth.decode_field(data, "public_key", 32)
    key_auth.verify(public_key, data, message(origin, action, username, nonce))
    label = data.get("label", "Sign-in key")
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 100 or any(ord(char) < 32 for char in label):
        raise ValueError("Enter a sign-in key label of up to 100 characters.")
    if action == "register":
        account_id = accounts.register_human(db, {**data, "username": username}, key_only=True)
    else:
        account_id = account["id"]
        if len(list_keys(db, account_id)) >= MAX_KEYS:
            raise ValueError("An account can store up to eight sign-in keys.")
    try:
        db.execute("INSERT INTO human_public_keys(key_id,account_id,public_key,label,created) VALUES (?,?,?,?,?)",
                   (secrets.token_hex(16), account_id, public_key, label.strip(), int(time.time())))
    except storage.INTEGRITY_ERRORS as error:
        raise ValueError("This public key already has a registration.") from error
    return account_id
