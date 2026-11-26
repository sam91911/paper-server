"""Register and verify WebAuthn credentials for existing human accounts."""

import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from . import accounts


SCHEMA = """
CREATE TABLE IF NOT EXISTS passkeys (
    credential_id BLOB PRIMARY KEY NOT NULL, account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    public_key BLOB NOT NULL, sign_count INTEGER NOT NULL, label TEXT NOT NULL, created INTEGER NOT NULL,
    origin TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS passkeys_account ON passkeys(account_id);
CREATE TABLE IF NOT EXISTS passkey_challenges (
    token TEXT PRIMARY KEY NOT NULL, challenge BLOB NOT NULL, origin TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('register','login')),
    session_hash BLOB, expires INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS passkey_challenges_expiry ON passkey_challenges(expires);
"""
MAX_PASSKEYS = 8
VERIFY_USER = UserVerificationRequirement.REQUIRED


def rp_id(origin):
    url = urlsplit(origin or "")
    if not url.hostname or (url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1")):
        raise ValueError("Passkeys require HTTPS or a supported localhost address.")
    return url.hostname


def user_handle(origin, account_id):
    return hashlib.sha256(f"paper-library:passkey:{origin}:{account_id}".encode()).digest()


def list_passkeys(db, account_id):
    return [
        {"id": bytes_to_base64url(bytes(row["credential_id"])), "label": row["label"], "created": row["created"]}
        for row in db.execute(
            "SELECT credential_id,label,created FROM passkeys WHERE account_id=? ORDER BY created,credential_id",
            (account_id,),
        )
    ]


def begin(db, origin, action, account=None, session=None):
    host = rp_id(origin)
    if action == "register":
        existing = list_passkeys(db, account["id"])
        if len(existing) >= MAX_PASSKEYS:
            raise ValueError("An account can have up to eight passkeys.")
        options = generate_registration_options(
            rp_id=host, rp_name="Paper Library", user_id=user_handle(origin, account["id"]),
            user_name=account["username"], user_display_name=account["display_name"] or account["username"],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED, user_verification=VERIFY_USER,
            ),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(item["id"])) for item in existing],
        )
    else:
        options = generate_authentication_options(rp_id=host, user_verification=VERIFY_USER)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM passkey_challenges WHERE expires<=?", (now,))
    db.execute("INSERT INTO passkey_challenges VALUES (?,?,?,?,?,?)",
               (token, options.challenge, origin, action, accounts.token_hash(session) if session else None, now + 300))
    return {"ceremony": token, "options": json.loads(options_to_json(options))}


def credential_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,1400}", value):
        raise ValueError("Invalid passkey credential.")
    try:
        return base64url_to_bytes(value)
    except ValueError as error:
        raise ValueError("Invalid passkey credential.") from error


def finish(db, origin, action, data, account=None, session=None):
    token = data.get("ceremony")
    credential = data.get("credential")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token) or not isinstance(credential, dict):
        raise ValueError("Start the passkey request again.")
    row = db.execute(
        "DELETE FROM passkey_challenges WHERE token=? AND origin=? AND action=? AND expires>? "
        "AND session_hash IS NOT DISTINCT FROM ? RETURNING challenge",
        (token, origin, action, int(time.time()), accounts.token_hash(session) if session else None),
    ).fetchone()
    if row is None:
        raise ValueError("The passkey request expired. Start again.")
    options = dict(expected_challenge=bytes(row["challenge"]), expected_rp_id=rp_id(origin),
                   expected_origin=origin, require_user_verification=True)
    response = credential.get("response")
    encoded_client = response.get("clientDataJSON") if isinstance(response, dict) else None
    if not isinstance(encoded_client, str) or len(encoded_client) > 8192:
        raise ValueError("Invalid passkey response.")
    client_data = json.loads(base64url_to_bytes(encoded_client))
    if not isinstance(client_data, dict) or client_data.get("crossOrigin", False) is not False:
        raise ValueError("Passkeys must be used from the library’s own page.")
    try:
        if action == "register":
            label = data.get("label")
            if not isinstance(label, str) or not label.strip() or len(label) > 100:
                raise ValueError("Enter a passkey label of up to 100 characters.")
            if len(list_passkeys(db, account["id"])) >= MAX_PASSKEYS:
                raise ValueError("An account can have up to eight passkeys.")
            result = verify_registration_response(credential=credential, **options)
            cursor = db.execute("INSERT INTO passkeys VALUES (?,?,?,?,?,?,?) ON CONFLICT(credential_id) DO NOTHING",
                                (result.credential_id, account["id"], result.credential_public_key,
                                 result.sign_count, label.strip(), int(time.time()), origin))
            if not cursor.rowcount:
                raise ValueError("This passkey is already registered.")
            return account["id"]
        key = db.execute(
            "SELECT p.* FROM passkeys p JOIN accounts a ON p.account_id=a.id "
            "WHERE p.credential_id=? AND p.origin=? AND a.role='user' AND a.disabled_at IS NULL",
            (credential_id(credential.get("id")), origin),
        ).fetchone()
        if key is None or response.get("userHandle") != bytes_to_base64url(
                user_handle(origin, key["account_id"])):
            raise ValueError("Passkey sign-in failed.")
        result = verify_authentication_response(credential=credential, credential_public_key=bytes(key["public_key"]),
                                                credential_current_sign_count=key["sign_count"], **options)
        db.execute("UPDATE passkeys SET sign_count=? WHERE credential_id=?",
                   (result.new_sign_count, key["credential_id"]))
        return key["account_id"]
    except WebAuthnException as error:
        raise ValueError("Passkey verification failed.") from error


def revoke(db, account, value):
    key = credential_id(value)
    if account["key_only"] and not db.execute(
        "SELECT 1 FROM human_public_keys WHERE account_id=? "
        "UNION ALL SELECT 1 FROM passkeys WHERE account_id=? AND credential_id<>? LIMIT 1",
        (account["id"], account["id"], key),
    ).fetchone():
        raise ValueError("Add a backup sign-in method before removing your last passkey.")
    if not db.execute("DELETE FROM passkeys WHERE credential_id=? AND account_id=?", (key, account["id"])).rowcount:
        raise ValueError("Passkey unavailable.")
    db.execute("DELETE FROM sessions WHERE account_id=?", (account["id"],))
