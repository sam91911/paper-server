"""Account session and application key HTTP operations."""

from . import accounts, library


def update_session(handler, data):
    if handler.headers.get("Authorization") is not None:
        raise accounts.SignInRequired
    token = handler.session_token()
    with library.connect(handler.server.database) as db:
        db.execute("BEGIN IMMEDIATE")
        if handler.path == "/api/sign-out":
            accounts.sign_out(db, token)
            account, token = None, ""
        elif handler.path == "/api/change-password":
            accounts.change_password(db, handler.require_account(db), data.get("current_password"),
                                     data.get("new_password"))
            account, token = None, ""
        else:
            if handler.path == "/api/register":
                accounts.register_human(db, data)
            account, token = accounts.sign_in(
                db, data.get("username"), data.get("password"),
                old_token=token,
            )
    max_age = accounts.SESSION_SECONDS if token else 0
    cookie = f"{accounts.COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"
    handler.send_json(200, {"account": account}, cookie=cookie)



def update_key(handler, db, data):
    account = handler.require_browser_account(db)
    if handler.path == "/api/application-keys":
        return {"key": accounts.create_key(db, account["id"], data.get("label"))}
    accounts.revoke_key(db, account["id"], data.get("key_id"))
