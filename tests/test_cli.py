import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from paper_app import accounts, library


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
