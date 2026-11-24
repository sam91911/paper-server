"""Run administrative commands on the terminal attached to the library server."""

import re
import shlex
import sys

from . import accounts, ai_accounts, database as storage, library


COMMANDS = {
    "help": (),
    "accounts": (),
    "set-account-role": ("USERNAME", "ROLE"),
    "revoke-human": ("USERNAME",),
    "invite-human": ("EMAIL",),
    "set-ai-operator": ("AGENT", "HUMAN"),
    "quit": (),
}


def completions(database, prior, prefix):
    if not prior:
        return [name for name in COMMANDS if name.startswith(prefix)]
    command, *arguments = prior
    if command == "set-account-role" and len(arguments) == 1:
        return [role for role in accounts.ROLES if role.startswith(prefix)]
    filters = {
        ("set-account-role", 0): "",
        ("revoke-human", 0): " AND role='user'",
        ("set-ai-operator", 0): " AND role='ai'",
        ("set-ai-operator", 1): " AND role='user' AND trusted=1",
    }
    scope = filters.get((command, len(arguments)))
    if scope is None or not re.fullmatch(r"[A-Za-z0-9_.-]{0,32}", prefix):
        return []
    pattern = prefix.lower().replace("_", "!_") + "%"
    with library.connect(database) as db:
        storage.begin(db)
        return [row["username"] for row in db.execute(
            "SELECT username FROM accounts WHERE disabled_at IS NULL AND LOWER(username) LIKE ? ESCAPE '!'"
            + scope + " ORDER BY username LIMIT 100", (pattern,),
        )]


def enable_completion(database):
    try:
        import readline
    except ImportError:
        return
    matches = []

    def complete(text, state):
        nonlocal matches
        if state == 0:
            try:
                line = readline.get_line_buffer()
                prior = shlex.split(line[:readline.get_begidx()])
                matches = completions(database, prior, text)
                if len(matches) == 1 and readline.get_endidx() == len(line):
                    matches[0] += " "
            except storage.ERRORS + (ValueError, OSError):
                matches = []
        return matches[state] if state < len(matches) else None

    readline.set_completer_delims(" \t\n")
    readline.set_completer(complete)
    readline.parse_and_bind("bind ^I rl_complete" if "libedit" in readline.__doc__ else "tab: complete")


def execute(server, command, arguments):
    if command == "help":
        return "\n".join(" ".join((name, *parameters)) for name, parameters in COMMANDS.items()) + (
            "\nRoles: user (trusted human), member, local, cloud."
        )
    with library.connect(server.database) as db:
        storage.begin(db, write=command != "accounts")
        if command == "accounts":
            rows = db.execute(
                f"SELECT a.username, {accounts.ROLE_SQL.format(alias='a')} AS role, a.disabled_at "
                "FROM accounts a ORDER BY a.username"
            )
            return "\n".join(f"{row['username']}\t{row['role']}" + (" (disabled)" if row["disabled_at"] is not None else "")
                             for row in rows) or "No accounts."
        if command == "set-account-role":
            username, role = arguments
            accounts.set_role(db, username, role)
            return f"Saved account {username} ({role})."
        if command == "revoke-human":
            accounts.revoke_human(db, arguments[0])
            return f"Revoked workspace access for {arguments[0]}."
        if command == "invite-human":
            token, _ = accounts.create_invite(db, arguments[0])
            origin = server.public_url or f"http://127.0.0.1:{server.server_port}"
            return accounts.invite_url(origin, token)
        ai_accounts.assign_operator(db, *arguments)
        return "AI operator saved."


def run(server, input_stream, output_stream):
    print("Admin console ready. Type help for commands.", file=output_stream, flush=True)
    terminal = input_stream is sys.stdin and output_stream is sys.stdout and input_stream.isatty() and output_stream.isatty()
    if terminal:
        enable_completion(server.database)
    while True:
        if terminal:
            try:
                line = input("paper> ")
            except EOFError:
                return
        else:
            line = input_stream.readline()
            if not line:
                return
        try:
            words = shlex.split(line)
            if not words:
                continue
            command, *arguments = words
            if command not in COMMANDS:
                raise ValueError("Unknown command. Type help.")
            if len(arguments) != len(COMMANDS[command]):
                raise ValueError("Usage: " + " ".join((command, *COMMANDS[command])))
            if command == "quit":
                server.shutdown()
                return
            print(execute(server, command, arguments), file=output_stream, flush=True)
        except (ValueError, OSError) as error:
            print(error, file=output_stream, flush=True)
        except storage.ERRORS:
            print("The library database could not execute this command.", file=output_stream, flush=True)
