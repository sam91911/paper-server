"""Optional Google OpenID Connect sign-in for the loopback server."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import database as storage
from . import accounts

COOKIE = "paper_google"
TTL = 600
SCHEMA = """
CREATE TABLE IF NOT EXISTS google_flows (
    state_hash BLOB PRIMARY KEY,
    verifier TEXT NOT NULL,
    nonce TEXT NOT NULL,
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS google_identities (
    subject TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id)
);
"""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def configuration(port, *, origin=None):
    client_id = os.environ.get("PAPER_GOOGLE_CLIENT_ID")
    secret = os.environ.get("PAPER_GOOGLE_CLIENT_SECRET")
    if not client_id and not secret:
        return None
    if not client_id or not secret:
        raise ValueError("Set both PAPER_GOOGLE_CLIENT_ID and PAPER_GOOGLE_CLIENT_SECRET.")
    try:
        from google.auth.transport import requests as _transport
        from google.oauth2 import id_token as _id_token
    except ImportError as error:
        raise ValueError("Install google-auth[requests] to enable Google sign-in.") from error
    return client_id, secret, f"{origin or f'http://127.0.0.1:{port}'}/auth/google/callback"


def begin(db, config):
    client_id, _, redirect_uri = config
    state, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    now = int(time.time())
    db.execute("DELETE FROM google_flows WHERE expires<=?", (now,))
    db.execute("INSERT INTO google_flows VALUES (?,?,?,?)",
               (accounts.token_hash(state), verifier, nonce, now + TTL))
    query = urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    return "https://accounts.google.com/o/oauth2/v2/auth?" + query, state


def consume(db, cookie_header, state):
    try:
        cookie = SimpleCookie(cookie_header or "").get(COOKIE)
    except CookieError:
        cookie = None
    if (not cookie or not cookie.value.isascii() or not state.isascii()
        or len(state) != 43 or not hmac.compare_digest(cookie.value, state)):
        raise ValueError("Google sign-in could not be verified.")
    key = accounts.token_hash(state)
    storage.begin(db, write=True)
    flow = db.execute(
        "SELECT verifier,nonce FROM google_flows WHERE state_hash=? AND expires>?",
        (key, int(time.time())),
    ).fetchone()
    if flow is None:
        raise ValueError("Google sign-in expired.")
    db.execute("DELETE FROM google_flows WHERE state_hash=?", (key,))
    return flow


def verify(config, code, flow):
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.id_token import verify_oauth2_token

    client_id, secret, redirect_uri = config
    payload = urlencode({
        "client_id": client_id, "client_secret": secret, "redirect_uri": redirect_uri,
        "code": code, "grant_type": "authorization_code", "code_verifier": flow["verifier"],
    }).encode("ascii")
    request = Request("https://oauth2.googleapis.com/token", payload,
                      {"Content-Type": "application/x-www-form-urlencoded"})
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        token = json.load(response)["id_token"]
    try:
        claims = verify_oauth2_token(token, GoogleRequest(), client_id)
    except Exception as error:
        # Keep provider errors and token details out of browser responses and server logs.
        raise ValueError("Google sign-in could not be verified.") from error
    if claims.get("nonce") != flow["nonce"] or claims.get("email_verified") is not True:
        raise ValueError("Google sign-in could not be verified.")
    return claims


def account(db, claims, *, invite_only=False):
    subject = claims.get("sub")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
        raise ValueError("Google sign-in could not be verified.")
    row = db.execute("SELECT i.account_id,a.disabled_at FROM google_identities i "
                     "JOIN accounts a ON a.id=i.account_id WHERE i.subject=?", (subject,)).fetchone()
    if row:
        if row["disabled_at"] is not None:
            raise ValueError("This workspace account is disabled.")
        return row["account_id"]
    if invite_only:
        raise ValueError("An invitation is required to join this workspace.")

    email = accounts.email_address(claims.get("email"))
    # Bind to Google's subject. A matching email never links a local password account.
    while True:
        username = "google-" + secrets.token_hex(6)
        if not db.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone():
            break
    try:
        name = accounts.person_name(claims.get("name"))
    except ValueError:
        name = username
    account_id = accounts.create_account(db, username, secrets.token_urlsafe(48), "user",
                                         display_name=name, email=email, trusted=False)
    db.execute("INSERT INTO google_identities VALUES (?,?)", (subject, account_id))
    return account_id
