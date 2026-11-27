"""Expiring repository-specific credentials for Git HTTPS."""

import base64
import binascii
import re
import secrets
import time

from . import accounts, sharing

SCHEMA = """CREATE TABLE IF NOT EXISTS git_tokens (
    id TEXT PRIMARY KEY, token_hash BLOB NOT NULL UNIQUE, account_id INTEGER NOT NULL REFERENCES accounts(id),
    kind TEXT NOT NULL, resource_id INTEGER NOT NULL, access TEXT NOT NULL CHECK(access IN ('read','write')),
    expires INTEGER NOT NULL
)"""
KINDS = ("documents", "experiments", "projects")
TOKEN = re.compile(r"pl_git_[A-Za-z0-9_-]{43}")


def list_tokens(db, account):
    return {"tokens": [dict(row) for row in db.execute(
        """SELECT id,kind,resource_id,access,expires FROM git_tokens
           WHERE account_id=? AND expires>? ORDER BY expires DESC,id""", (account["id"], int(time.time())))]}


def update(db, account, data):
    from . import git_repos
    if data.get("action") == "revoke":
        token_id = data.get("id")
        if not isinstance(token_id, str) or not re.fullmatch(r"[a-f0-9]{24}", token_id):
            raise ValueError("Choose a Git token.")
        db.execute("DELETE FROM git_tokens WHERE id=? AND account_id=?", (token_id, account["id"]))
        return list_tokens(db, account)
    kind, resource, access, days = (data.get(key) for key in ("kind", "resource_id", "access", "days"))
    if (data.get("action") != "create" or kind not in KINDS or type(resource) is not int or not 0 < resource < 2**63
            or access not in ("read", "write") or type(days) is not int or not 1 <= days <= 90):
        raise ValueError("Choose one repository, read or write access, and an expiry of 1–90 days.")
    git_repos.resource_scope(db, account, kind, resource, writing=access == "write")
    token = "pl_git_" + secrets.token_urlsafe(32)
    token_id = secrets.token_hex(12)
    db.execute("DELETE FROM git_tokens WHERE account_id=? AND expires<=?", (account["id"], int(time.time())))
    db.execute("INSERT INTO git_tokens VALUES (?,?,?,?,?,?,?)",
               (token_id, accounts.token_hash(token), account["id"], kind, resource, access, int(time.time()) + days * 86400))
    return {**list_tokens(db, account), "token": token}


def authenticate(handler, db, kind, resource, writing):
    authorization = handler.headers.get("Authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "basic":
        try:
            username, _, token = base64.b64decode(credentials, validate=True).decode("ascii").partition(":")
        except (UnicodeError, binascii.Error):
            raise accounts.SignInRequired from None
    elif scheme.lower() == "bearer" and credentials.startswith("pl_git_"):
        username, token = None, credentials
    else:
        return handler.require_account(db)
    if not TOKEN.fullmatch(token):
        raise accounts.SignInRequired
    row = db.execute(f"""SELECT a.id,a.username,{accounts.ROLE_SQL.format(alias='a')} AS role,
                                t.kind,t.resource_id,t.access FROM git_tokens t JOIN accounts a ON a.id=t.account_id
                         WHERE t.token_hash=? AND t.expires>? AND a.disabled_at IS NULL""",
                     (accounts.token_hash(token), int(time.time()))).fetchone()
    if not row or (username is not None and username.casefold() != row["username"].casefold()):
        raise accounts.SignInRequired
    if (row["kind"], row["resource_id"]) != (kind, resource) or (writing and row["access"] != "write"):
        raise sharing.AccessDenied
    return dict(row)
