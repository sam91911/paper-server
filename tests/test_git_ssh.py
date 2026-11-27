import json
import os
import pwd
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_app import accounts, experiments, git_ssh, library, projects, sharing
from paper_client.agent import encode
from paper_client.ssh_key import export


class GitSSHTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / "library.sqlite3"
        self.config = self.root / "ssh.toml"
        self.config.write_text(f'database = "{self.db}"\n', encoding="utf-8")
        library.initialize(self.db)
        self.human_key = Ed25519PrivateKey.generate()
        self.agent_key = Ed25519PrivateKey.generate()
        with library.connect(self.db) as db:
            self.owner = {"id": accounts.create_account(db, "owner", "", "user", key_only=True), "role": "user"}
            self.agent = {"id": accounts.create_account(db, "writer-ai", "", "local", key_only=True), "role": "local"}
            db.execute("INSERT INTO human_public_keys(key_id,account_id,public_key,label) VALUES (?,?,?,'Test')",
                       ("1" * 32, self.owner["id"], self.human_key.public_key().public_bytes_raw()))
            db.execute("INSERT INTO ai_public_keys(account_id,public_key) VALUES (?,?)",
                       (self.agent["id"], self.agent_key.public_key().public_bytes_raw()))
            self.document = sharing.save_document(db, self.owner, {"title": "Original", "markdown": "First"})
            self.experiment = experiments.save_experiment(db, self.agent, {"title": "Experiment"})

    def test_key_export_and_key_lookup_follow_revocation(self):
        for key, human in ((self.human_key, True), (self.agent_key, False)):
            identity = self.root / f"{human}.json"
            seed = encode(key.private_bytes_raw())
            if human:
                fields = dict(key={"kty": "OKP", "crv": "Ed25519", "d": seed,
                                   "x": encode(key.public_key().public_bytes_raw())})
            else:
                fields = dict(private_key=seed)
            identity.write_text(json.dumps(fields))
            destination = self.root / f"{human}.ssh"
            export(identity, destination)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            restored = serialization.load_ssh_private_key(destination.read_bytes(), None)
            self.assertEqual(restored.public_key().public_bytes_raw(), key.public_key().public_bytes_raw())
            with self.assertRaises(FileExistsError):
                export(identity, destination)
            kind, blob = key.public_key().public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH,
            ).decode().split()
            line = git_ssh.authorized_key(self.config, kind, blob)
            self.assertTrue(line.startswith('restrict,command="'))
            self.assertTrue(line.endswith(f" {kind} {blob}"))
            self.assertIsNone(git_ssh.authorized_key(self.config, "ssh-rsa", blob))
        with library.connect(self.db) as db:
            accounts.revoke_human(db, "owner")
            db.execute("UPDATE ai_public_keys SET public_key=? WHERE account_id=?",
                       (Ed25519PrivateKey.generate().public_key().public_bytes_raw(), self.agent["id"]))
        for key in (self.human_key, self.agent_key):
            kind, blob = key.public_key().public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH,
            ).decode().split()
            self.assertIsNone(git_ssh.authorized_key(self.config, kind, blob))
        for garbage in ("id", "git-upload-pack /etc", "git-receive-pack /git/documents/1.git; id"):
            with self.assertRaises(ValueError):
                git_ssh.parse_command(garbage)

    @unittest.skipUnless(shutil.which("git"), "Git is required")
    def test_git_native_commands_use_registered_identity_and_apply_hooks(self):
        ssh = self.root / "ssh-test"
        root = str(Path(__file__).resolve().parents[1])
        ssh.write_text(
            "#!/bin/sh\n"
            "for argument do export SSH_ORIGINAL_COMMAND=\"$argument\"; done\n"
            f"export PYTHONPATH={shlex.quote(root)}\n"
            f"exec {shlex.join([sys.executable, '-m', 'paper_app.git_ssh', '--config', str(self.config), 'serve'])} "
            '"$TEST_SSH_KEY"\n',
        )
        ssh.chmod(0o700)

        def transport(key):
            return {"GIT_SSH_COMMAND": str(ssh), "GIT_SSH_VARIANT": "simple",
                    "TEST_SSH_KEY": key.public_key().public_bytes_raw().hex()}

        self.check_git_workflow("ssh://git@library.example", transport)

    @unittest.skipUnless(os.getenv("PAPER_TEST_SSHD"), "Set PAPER_TEST_SSHD to run a live OpenSSH test")
    def test_live_openssh_listener(self):
        sshd = os.environ["PAPER_TEST_SSHD"]
        user = pwd.getpwuid(os.getuid()).pw_name
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        host_key = self.root / "host"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", host_key], check=True, timeout=10)
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text(
            f"[127.0.0.1]:{port} " + host_key.with_suffix(".pub").read_text(encoding="utf-8"), encoding="utf-8",
        )
        template = Path(__file__).resolve().parents[1] / "deploy" / "sshd-paper-library.conf"
        config = self.root / "sshd_config"
        config.write_text(
            template.read_text(encoding="utf-8")
            .replace("Port 2222", f"Port {port}\nListenAddress 127.0.0.1")
            .replace("/etc/ssh/ssh_host_ed25519_key", str(host_key))
            .replace("/run/paper-library-git-sshd.pid", str(self.root / "sshd.pid"))
            .replace("/opt/paper-library/.venv/bin/python", sys.executable)
            .replace("/etc/paper-library-git.toml", str(self.config))
            .replace("AllowUsers paper-library", f"AllowUsers {user}")
            .replace("AuthorizedKeysCommandUser paper-library", f"AuthorizedKeysCommandUser {user}"),
            encoding="utf-8",
        )
        subprocess.run([sshd, "-t", "-f", config], check=True, timeout=10)

        def ssh_command(key):
            name = key.public_key().public_bytes_raw().hex()
            destination = self.root / name
            if not destination.exists():
                identity = destination.with_suffix(".json")
                identity.write_text(json.dumps({"private_key": encode(key.private_bytes_raw())}), encoding="utf-8")
                export(identity, destination)
            return ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                    "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=yes",
                    "-o", f"UserKnownHostsFile={known_hosts}", "-i", str(destination)]

        def transport(key):
            return {"GIT_SSH_COMMAND": shlex.join(ssh_command(key)), "GIT_SSH_VARIANT": "ssh"}

        log = self.root / "sshd.log"
        with log.open("wb") as output, subprocess.Popen([sshd, "-D", "-e", "-f", config], stderr=output) as daemon:
            try:
                for _ in range(50):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=1) as connection:
                            with connection.makefile("rb") as stream:
                                self.assertEqual(stream.read(4), b"SSH-")
                        break
                    except ConnectionError:
                        if daemon.poll() is not None:
                            self.fail("The test OpenSSH listener exited during startup.")
                        time.sleep(0.1)
                else:
                    self.fail("The test OpenSSH listener did not start.")

                self.check_git_workflow(f"ssh://{user}@127.0.0.1:{port}", transport)
                with library.connect(self.db) as db:
                    accounts.revoke_human(db, "owner")

                def remote(key, command):
                    return subprocess.run([*ssh_command(key), "-p", str(port), f"{user}@127.0.0.1", command],
                                          capture_output=True, timeout=10)

                shell = remote(self.agent_key, "id")
                self.assertNotEqual(shell.returncode, 0)
                self.assertIn(b"Use Git clone, fetch, or push", shell.stderr)
                denied = remote(self.human_key, f"git-upload-pack /git/documents/{self.document}.git")
                self.assertEqual(denied.returncode, 255)
                self.assertIn(b"Permission denied (publickey)", denied.stderr)
            except (AssertionError, OSError, subprocess.SubprocessError):
                print(log.read_text(encoding="utf-8"), file=sys.stderr)
                raise
            finally:
                if daemon.poll() is None:
                    daemon.terminate()
                    try:
                        daemon.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        daemon.kill()

    def check_git_workflow(self, origin, transport):
        def git(path, key, *args, expected=True):
            env = {**os.environ, **transport(key)}
            result = subprocess.run(["git", "-C", path, *args], env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode == 0, expected, result.stderr.decode())
            return result

        doc_url = f"{origin}/git/documents/{self.document}.git"
        git(self.root, self.agent_key, "clone", doc_url, "forbidden", expected=False)
        git(self.root, self.human_key, "clone", doc_url, "doc")
        doc = self.root / "doc"
        (doc / "document.md").write_text("Updated by SSH")
        git(doc, self.human_key, "add", ".")
        git(doc, self.human_key, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "Markdown")
        git(doc, self.human_key, "push")
        with library.connect(self.db) as db:
            self.assertEqual(sharing.document_for(db, self.owner, self.document)["markdown"], "Updated by SSH")
        git(self.root, self.human_key, "clone", doc_url, "copy")
        self.assertEqual((self.root / "copy/document.md").read_text(), "Updated by SSH")
        exp_url = f"{origin}/git/experiments/{self.experiment}.git"
        git(self.root, self.agent_key, "clone", "--branch", "source", exp_url, "source")
        source = self.root / "source"
        (source / "code.py").write_text("print('run')\n")
        git(source, self.agent_key, "add", ".")
        git(source, self.agent_key, "-c", "user.name=Agent", "-c", "user.email=agent@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "Source code")
        git(source, self.agent_key, "push")
        with library.connect(self.db) as db:
            saved = experiments.require_experiment(db, self.experiment, self.agent)["source_commit"]
            self.assertEqual(saved, git(source, self.agent_key, "rev-parse", "HEAD").stdout.decode().strip())


        with library.connect(self.db) as db:
            project = projects.update(db, self.owner, {"action": "create", "title": "Project"}, 0)["project"]
            projects.update(db, self.owner, {"action": "share", "id": project["id"],
                                            "username": "writer-ai", "access": "write"}, 0)
            projects.update(db, self.agent, {"action": "link_experiment", "id": project["id"],
                                            "experiment_id": self.experiment}, 0)
        project_url = origin + project["git_path"]
        branch = f"experiment/{self.experiment}"
        git(self.root, self.agent_key, "clone", "--branch", branch, project_url, "project")
        work = self.root / "project"
        (work / "simulation.py").write_text("print(42)\n")
        git(work, self.agent_key, "add", ".")
        git(work, self.agent_key, "-c", "user.name=Agent", "-c", "user.email=agent@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "Update simulation")
        git(work, self.agent_key, "push")
        git(self.root, self.human_key, "clone", "--branch", branch, project_url, "project-copy")
        self.assertTrue((self.root / "project-copy/simulation.py").exists())
