import io
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from paper_app import accounts, admin_console, library


LAUNCHER = Path(__file__).resolve().parents[1] / "run_paper_server.sh"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def run_launcher(self, *arguments):
        environment = dict(os.environ)
        environment.pop("PAPER_DATABASE_URL", None)
        environment.pop("PAPER_PUBLIC_URL", None)
        return subprocess.run(
            ["bash", str(LAUNCHER), *arguments],
            cwd=self.directory, env=environment, capture_output=True, text=True, timeout=10,
        )

    def test_launcher_accepts_server_options_and_caller_relative_paths(self):
        metrics = self.directory / "metrics file.csv"
        metrics.write_text("paper,page,metric,value,unit,conditions,evidence\nsource.pdf,1,power,5,W,,\n")
        result = self.run_launcher("library file.sqlite3", "--import-csv", metrics.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        with library.connect(self.directory / "library file.sqlite3") as db:
            self.assertEqual(db.execute("SELECT path FROM papers").fetchone()[0], str(self.directory / "source.pdf"))

    def test_conflicting_admin_commands_fail_before_opening_the_database(self):
        result = self.run_launcher("library.sqlite3", "--import-csv", "metrics.csv", "--invite-human", "a@example.org")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("not allowed with argument", result.stderr)
        self.assertFalse((self.directory / "library.sqlite3").exists())

    def test_bash_completion_matches_launcher_options_paths_and_roles(self):
        completion = LAUNCHER.parent / "scripts" / "paper-server-completion.bash"
        database = self.directory / "library notes.sqlite3"
        database.touch()

        def complete(*words):
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; shift; COMP_WORDS=(./run_paper_server.sh "$@"); '
                 'COMP_CWORD=$((${#COMP_WORDS[@]} - 1)); _paper_server_complete; printf "%s\\n" "${COMPREPLY[@]}"',
                 "completion", str(completion), *words], cwd=self.directory, capture_output=True, text=True, check=True,
            )
            return result.stdout.splitlines()

        flags = set(re.findall(r"(?<![\w-])--[a-z][\w-]*", self.run_launcher("--help").stdout))
        self.assertEqual(set(complete("--")), flags)
        self.assertEqual(complete("library"), [database.name])
        self.assertEqual(complete("--database", "library"), [database.name])
        self.assertEqual(complete("--database=library"), [f"--database={database.name}"])
        self.assertEqual(complete("library notes.sqlite3", "--set-account-role", "reader", "u"), ["user"])

    def test_human_invitation_prints_signup_url_on_public_origin(self):
        result = self.run_launcher("library.sqlite3", "--invite-human", "reader@example.org",
                                   "--public-url", "https://papers.example.org:8443")
        self.assertEqual(result.returncode, 0, result.stderr)
        prefix = "https://papers.example.org:8443/account#invite="
        self.assertTrue(result.stdout.startswith(prefix))
        token = result.stdout.strip().removeprefix(prefix)
        self.assertTrue(accounts.valid_token(token))
        with library.connect(self.directory / "library.sqlite3") as db:
            row = db.execute("SELECT email FROM human_invites WHERE token_hash=?", (accounts.token_hash(token),)).fetchone()
            self.assertEqual(row["email"], "reader@example.org")

    def test_interactive_console_manages_running_library(self):
        database = self.directory / "library.sqlite3"
        library.initialize(database)
        with library.connect(database) as db:
            human = accounts.create_account(db, "reader", "sample reader password", "member")
            agent = accounts.create_account(db, "researcher", "sample agent password", "local")
            old_session = accounts.start_session(db, human, None)
        shutdown_calls = []
        server = SimpleNamespace(database=database, public_url="https://papers.example.org", server_port=8765,
                                 shutdown=lambda: shutdown_calls.append(True))
        output = io.StringIO()
        commands = io.StringIO("help\naccounts\nset-account-role reader\nset-account-role reader user\n"
                               "set-ai-operator researcher reader\ninvite-human friend@example.org\naccounts\nquit\n")
        admin_console.run(server, commands, output)
        transcript = output.getvalue()
        self.assertIn("reader\tmember", transcript)
        self.assertIn("Usage: set-account-role USERNAME ROLE", transcript)
        self.assertIn("reader\tuser", transcript)
        self.assertEqual(shutdown_calls, [True])
        prefix = "https://papers.example.org/account#invite="
        token, = (line.removeprefix(prefix) for line in transcript.splitlines() if line.startswith(prefix))
        with library.connect(database) as db:
            self.assertIsNone(accounts.current_account(db, old_session))
            self.assertEqual(db.execute("SELECT operator_id FROM ai_operators WHERE agent_id=?", (agent,)).fetchone()[0], human)
            invite = db.execute("SELECT email,role FROM human_invites WHERE token_hash=?", (accounts.token_hash(token),)).fetchone()
            self.assertEqual(tuple(invite), ("friend@example.org", "user"))
        self.assertEqual(admin_console.completions(database, [], "set-account-r"), ["set-account-role"])
        self.assertEqual(admin_console.completions(database, ["set-account-role"], "read"), ["reader"])
        self.assertEqual(admin_console.completions(database, ["set-account-role", "reader"], "u"), ["user"])
        self.assertEqual(admin_console.completions(database, ["set-ai-operator"], "res"), ["researcher"])
        self.assertEqual(admin_console.completions(database, ["set-ai-operator", "researcher"], ""), ["reader"])
