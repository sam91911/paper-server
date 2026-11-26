"""Account session and application key HTTP operations."""

from . import database as storage
from . import accounts, human_keys, library, passkeys

KEY_ACTIONS = {f"/api/human-key/{action}": action for action in ("challenge", "register", "login", "attach", "revoke")}
PASSKEY_ACTIONS = {f"/api/passkeys/{action}": action for action in
                   ("register-options", "register", "login-options", "login", "revoke")}
SESSION_ROUTES = {"/api/register", "/api/sign-in", "/api/sign-out", "/api/change-password",
                  *KEY_ACTIONS, *PASSKEY_ACTIONS}


def use_passkey(handler, db, action, data, token):
    origin = handler.request_origin()
    if action in ("login-options", "login"):
        if action == "login-options":
            return passkeys.begin(db, origin, "login"), None
        account_id = passkeys.finish(db, origin, "login", data)
        token = accounts.start_session(db, account_id, token)
        return {"account": accounts.current_account(db, token)}, token
    account = handler.require_browser_account(db)
    if account["role"] not in ("user", "member"):
        raise accounts.SignInRequired
    if action == "register-options":
        return passkeys.begin(db, origin, "register", account, token), None
    if action == "register":
        passkeys.finish(db, origin, "register", data, account, token)
        return {"passkeys": passkeys.list_passkeys(db, account["id"])}, None
    passkeys.revoke(db, account, data.get("id"))
    return {"account": None}, ""


def use_human_key(handler, db, action, data, token):
    account = None
    if action in ("attach", "revoke") or (action == "challenge" and data.get("action") == "attach"):
        account = handler.require_account(db)
        if account["role"] not in ("user", "member"):
            raise accounts.SignInRequired
    if action == "revoke":
        human_keys.revoke(db, account, data.get("key_id"))
        return {"account": None}, ""
    origin = handler.request_origin()
    if action == "challenge":
        return human_keys.challenge(db, origin, data, account), None
    account_id = human_keys.finish(db, origin, action, data, account,
                                   invite_only=getattr(handler.server, "invite_only", False))
    token = accounts.start_session(db, account_id, token)
    return {"account": accounts.current_account(db, token)}, token


def use_password_session(handler, db, data, token):
    if handler.path == "/api/sign-out":
        accounts.sign_out(db, token)
        return {"account": None}, ""
    if handler.path == "/api/change-password":
        accounts.change_password(db, handler.require_account(db), data.get("current_password"), data.get("new_password"))
        return {"account": None}, ""
    if handler.path == "/api/register":
        accounts.register_human(db, data, invite_only=getattr(handler.server, "invite_only", False))
    account, token = accounts.sign_in(db, data.get("username"), data.get("password"), old_token=token)
    return {"account": account}, token


def update_session(handler, data):
    if handler.headers.get("Authorization") is not None:
        raise accounts.SignInRequired
    token = handler.session_token()
    with library.connect(handler.server.database) as db:
        storage.begin(db, write=True)
        if handler.path in KEY_ACTIONS:
            result, token = use_human_key(handler, db, KEY_ACTIONS[handler.path], data, token)
        elif handler.path in PASSKEY_ACTIONS:
            result, token = use_passkey(handler, db, PASSKEY_ACTIONS[handler.path], data, token)
        else:
            result, token = use_password_session(handler, db, data, token)
    handler.send_json(200, result, cookie=handler.session_cookie(token) if token is not None else None)


def update_key(handler, db, data):
    account = handler.require_browser_account(db)
    if handler.path == "/api/application-keys":
        return {"key": accounts.create_key(db, account["id"], data.get("label"))}
    accounts.revoke_key(db, account["id"], data.get("key_id"))
