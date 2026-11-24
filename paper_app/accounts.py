"""Local accounts and expiring browser sessions."""

import hashlib
import hmac
import re
import secrets
import time
from http.cookies import CookieError, SimpleCookie

from . import database as storage

COOKIE = "paper_session"
ROLES = ("user", "member", "local", "cloud")
ROLE_SQL = """CASE WHEN {alias}.role = 'user' THEN
    CASE WHEN {alias}.trusted=1 THEN 'user' ELSE 'member' END ELSE {alias}.ai_location END"""
SESSION_SECONDS = 7 * 24 * 60 * 60
AI_SESSION_PREFIX = "pl_ai_"
TOKEN_PATTERN = r"[A-Za-z0-9_-]{43}"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash BLOB NOT NULL,
    salt BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash BLOB PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS human_invites (
    token_hash BLOB PRIMARY KEY, email TEXT NOT NULL COLLATE NOCASE, expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS application_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL REFERENCES accounts(id),
    label TEXT NOT NULL, token_hash BLOB NOT NULL UNIQUE,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS comment_authors (
    comment_id INTEGER PRIMARY KEY REFERENCES comments(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    kind TEXT NOT NULL CHECK (kind IN ('user', 'ai'))
);
"""


class SignInRequired(Exception):
    pass


class CommentAccessDenied(Exception):
    pass


def password_hash(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=32768, r=8, p=3,
                          maxmem=64 * 1024 * 1024)


def token_hash(token):
    return hashlib.sha256(token.encode("ascii")).digest()


def valid_token(value):
    return isinstance(value, str) and re.fullmatch(TOKEN_PATTERN, value) is not None


def read_token(header):
    cookie = SimpleCookie()
    try:
        cookie.load(header or "")
    except CookieError:
        return None
    token = cookie.get(COOKIE)
    if token and valid_token(token.value):
        return token.value
    return None


def initialize(db):
    columns = {row["name"] for row in db.execute("PRAGMA table_info(accounts)")}
    for name, declaration in (
        ("role", "TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'ai'))"),
        ("ai_location", "TEXT NOT NULL DEFAULT 'cloud' CHECK (ai_location IN ('local', 'cloud'))"),
        ("display_name", "TEXT NOT NULL DEFAULT ''"),
        ("email", "TEXT COLLATE NOCASE"),
        ("trusted", "INTEGER NOT NULL DEFAULT 1 CHECK (trusted IN (0,1))"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE accounts ADD COLUMN {name} {declaration}")
    db.execute("DROP INDEX IF EXISTS accounts_email")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS trusted_account_email ON accounts(email) WHERE trusted=1")


def current_account(db, token, *, application_key=False, ai_session=False):
    if token is None:
        return None
    join = ("JOIN application_keys s ON a.id=s.account_id WHERE s.token_hash=?"
            if application_key else "JOIN sessions s ON a.id=s.account_id WHERE s.token_hash=? AND s.expires>?")
    if ai_session:
        join += " AND a.role='ai'"
    params = (token_hash(token),) if application_key else (token_hash(token), int(time.time()))
    row = db.execute(
        f"SELECT a.id, a.username, a.display_name, a.email, {ROLE_SQL.format(alias='a')} AS role, "
        f"EXISTS(SELECT 1 FROM google_identities i WHERE i.account_id=a.id) AS google_only, "
        f"EXISTS(SELECT 1 FROM human_public_keys k WHERE k.account_id=a.id) AS has_private_key, "
        f"length(a.password_hash)=0 AS key_only "
        f"FROM accounts a {join}", params,
    ).fetchone()
    if row is None:
        return None
    return {**dict(row), "has_private_key": bool(row["has_private_key"]), "key_only": bool(row["key_only"])}


def email_address(email):
    email = email.strip().lower() if isinstance(email, str) else ""
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", email):
        raise ValueError("Enter a valid email address.")
    return email


def person_name(name):
    name = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(name) <= 120 or any(ord(char) < 32 for char in name):
        raise ValueError("Enter a name of up to 120 characters.")
    return name


def create_invite(db, email):
    email = email_address(email)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM human_invites WHERE expires<=? OR email=?", (now, email))
    db.execute("INSERT INTO human_invites VALUES (?,?,?)", (token_hash(token), email, now + 86400))
    return token


def register_human(db, data, *, key_only=False):
    email = email_address(data.get("email"))
    token = data.get("invite") or ""
    if token:
        message = "Enter a valid invitation for this email address or leave it blank."
        if not valid_token(token):
            raise ValueError(message)
        used = db.execute(
            "DELETE FROM human_invites WHERE token_hash=? AND email=? AND expires>?",
            (token_hash(token), email, int(time.time())),
        ).rowcount
        if not used:
            raise ValueError(message)
    try:
        return create_account(db, data.get("username"), data.get("password"), "user",
                              display_name=person_name(data.get("display_name")), email=email, trusted=bool(token),
                              key_only=key_only)
    except storage.INTEGRITY_ERRORS as error:
        raise ValueError("That username or email address is already in use.") from error


def create_key(db, account_id, label):
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 100:
        raise ValueError("Enter a label of up to 100 characters.")
    token = "pl_" + secrets.token_urlsafe(32)
    db.execute("INSERT INTO application_keys(account_id,label,token_hash) VALUES (?,?,?)",
               (account_id, label.strip(), token_hash(token)))
    return token


def list_keys(db, account_id):
    return [dict(row) for row in db.execute(
        "SELECT id,label,created FROM application_keys WHERE account_id=? ORDER BY id", (account_id,),
    )]


def revoke_key(db, account_id, key_id):
    if type(key_id) is not int or not db.execute(
        "DELETE FROM application_keys WHERE id=? AND account_id=?", (key_id, account_id),
    ).rowcount:
        raise ValueError("Application key not found.")


def sign_out(db, token):
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))


def validate_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Use a password of 12–256 characters.")


def identity(username):
    username = username.strip() if isinstance(username, str) else ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,31}", username):
        raise ValueError("Use a username of 2–32 letters, numbers, dots, underscores, or hyphens.")
    return username


def suggest_usernames(db, query):
    query = query.strip()
    if not 2 <= len(query) <= 32 or any(ord(char) < 32 for char in query):
        return []
    pattern = query.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    return [dict(row) for row in db.execute(
        "SELECT username,display_name FROM accounts "
        "WHERE LOWER(username) LIKE LOWER(?) ESCAPE '!' OR LOWER(display_name) LIKE LOWER(?) ESCAPE '!' "
        "ORDER BY (LOWER(username) LIKE LOWER(?) ESCAPE '!') DESC,username LIMIT 8",
        (pattern, pattern, pattern),
    )]


def role_fields(role):
    if role not in ROLES:
        raise ValueError("Choose user, member, local, or cloud.")
    return ("user" if role in ("user", "member") else "ai", "local" if role == "local" else "cloud")


def create_account(db, username, password, role, *, display_name="", email=None, trusted=True, key_only=False):
    username = identity(username)
    salt = secrets.token_bytes(16)
    digest = b""
    if not key_only:
        validate_password(password)
        digest = password_hash(password, salt)
    return db.execute(
        "INSERT INTO accounts(username,password_hash,salt,role,ai_location,display_name,email,trusted) "
        "VALUES (?,?,?,?,?,?,?,?) RETURNING id",
        (username, digest, salt, *role_fields(role), display_name, email, int(trusted and role != "member")),
    ).fetchone()[0]


def set_role(db, username, role):
    row = db.execute("UPDATE accounts SET role=?,ai_location=?,trusted=? WHERE username=? RETURNING id",
                     (*role_fields(role), int(role != "member"), identity(username))).fetchone()
    if row is None:
        raise ValueError("Account not found.")
    other_keys = "ai_public_keys" if role in ("user", "member") else "human_public_keys"
    for table in ("sessions", "application_keys", other_keys):
        db.execute(f"DELETE FROM {table} WHERE account_id=?", (row["id"],))


def authenticate(db, username, password):
    validate_password(password)
    row = db.execute(
        f"SELECT a.*, {ROLE_SQL.format(alias='a')} AS effective_role FROM accounts a WHERE username=?",
        (identity(username),),
    ).fetchone()
    digest = password_hash(password, row["salt"] if row else bytes(16))
    if not row or not hmac.compare_digest(digest, row["password_hash"]):
        raise ValueError("Incorrect username or password.")
    return {"id": row["id"], "username": row["username"], "role": row["effective_role"],
            "display_name": row["display_name"], "email": row["email"]}


def change_password(db, account, current_password, new_password):
    authenticate(db, account["username"], current_password)
    validate_password(new_password)
    salt = secrets.token_bytes(16)
    db.execute("UPDATE accounts SET password_hash=?,salt=? WHERE id=?",
               (password_hash(new_password, salt), salt, account["id"]))
    for table in ("sessions", "application_keys"):
        db.execute(f"DELETE FROM {table} WHERE account_id=?", (account["id"],))


def sign_in(db, username, password, *, old_token):
    account = authenticate(db, username, password)
    return account, start_session(db, account["id"], old_token)


def start_session(db, account_id, old_token, *, prefix="", expires_in=SESSION_SECONDS):
    token = prefix + secrets.token_urlsafe(32)
    now = int(time.time())
    sign_out(db, old_token)
    db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
    db.execute("INSERT INTO sessions VALUES (?,?,?)",
               (token_hash(token), account_id, now + expires_in))
    return token
