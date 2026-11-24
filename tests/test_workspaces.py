import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_app import accounts, google_signin, library
from paper_client import agent
from test_skill_api import request


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.labs = {}
        for name in ("alpha", "beta"):
            database = Path(temp.name) / f"{name}.sqlite3"
            library.initialize(database)
            with library.connect(database) as db:
                admin = accounts.create_account(db, "researcher", "test only password", "user")
                self.labs[name] = (database, accounts.start_session(db, admin, None))

    def api(self, lab, path, *, expected=200, headers=None, **kwargs):
        host = f"{lab}.papers.example.org"
        status, response = request(
            self.labs[lab][0], path, headers={"Host": host, **(headers or {})},
            public_url=f"https://{host}", invite_only=True, **kwargs,
        )
        self.assertEqual(status, expected, str(response)[:500])
        return response

    def test_membership_requires_local_invitation(self):
        alpha = self.labs["alpha"][1]
        data = {"username": "colleague", "display_name": "Colleague", "email": "colleague@example.org"}
        signup = dict(data, password="one-time enrollment password")
        self.assertTrue(self.api("alpha", "/api/account")["invitation_required"])
        self.api("alpha", "/api/register", data=signup, expected=400)
        invite_url = self.api("alpha", "/api/human-invitations", cookie=alpha, data={
            "email": data["email"], "role": "member",
        })["invitation_url"]
        self.assertTrue(invite_url.startswith("https://alpha.papers.example.org/account#invite="))
        invite = invite_url.split("=", 1)[1]
        self.api("beta", "/api/register", data=dict(signup, invite=invite), expected=400)

        private_key = Ed25519PrivateKey.generate()
        challenge = self.api("alpha", "/api/human-key/challenge", data={"action": "register", "username": data["username"]})
        enrollment = dict(data, public_key=agent.encode(private_key.public_key().public_bytes_raw()),
                          challenge=challenge["challenge"], signature=agent.encode(private_key.sign(challenge["message"].encode())))
        self.api("alpha", "/api/human-key/register", data=enrollment, expected=400)
        enrolled = self.api("alpha", "/api/human-key/register", data=dict(enrollment, invite=invite))["account"]
        self.assertEqual(enrolled["role"], "member")
        self.api("alpha", "/api/register", data=dict(signup, invite=invite), expected=400)

        with library.connect(self.labs["alpha"][0]) as db:
            with self.assertRaisesRegex(ValueError, "invitation is required"):
                google_signin.account(db, {"sub": "new-member", "email": "new-member@example.org"}, invite_only=True)
            db.execute("INSERT INTO google_identities VALUES ('existing-member',?)", (enrolled["id"],))
            self.assertEqual(google_signin.account(db, {"sub": "existing-member"}, invite_only=True), enrolled["id"])

    def test_two_workspaces_keep_sessions_agents_and_artifacts_separate(self):
        for lab, (_database, admin) in self.labs.items():
            with patch("paper_app.pdf.extract_pdf", return_value=([], False)):
                self.api(lab, "/api/papers", cookie=admin, binary=f"%PDF-{lab}".encode(), headers={
                    "Content-Type": "application/pdf", "X-Paper-Filename": f"{lab}.pdf", "X-Paper-Audience": "all",
                })
            self.api(lab, "/api/metadata", cookie=admin, data={"paper_id": 1, "title": f"{lab} research"})
            self.api(lab, "/api/documents", cookie=admin, data={"title": f"{lab} notes", "markdown": lab, "audience": "all"})
            exp = self.api(lab, "/api/experiments", cookie=admin, data={"title": f"{lab} experiment", "audience": "all"})["id"]
            self.assertEqual(exp, 1)
            archive = BytesIO()
            with ZipFile(archive, "w") as bundle:
                bundle.writestr(f"{lab}.txt", lab)
            artifact = self.api(lab, "/api/research-upload", cookie=admin, binary=archive.getvalue(), headers={
                "Content-Type": "application/octet-stream", "X-Research-Metadata": quote(json.dumps({
                    "experiment_id": 1, "kind": "code", "title": f"{lab} source", "filename": "source.zip", "audience": "all",
                })),
            })
            self.assertEqual(artifact["version_id"], 1)

        alpha, beta = (self.labs[lab][1] for lab in ("alpha", "beta"))
        self.api("beta", "/api/account", cookie=alpha, headers={"Host": "alpha.papers.example.org"}, expected=403)
        self.api("beta", "/api/account", cookie=beta, headers={"Origin": "https://alpha.papers.example.org"}, expected=403)
        self.assertIsNone(self.api("beta", "/api/account", cookie=alpha)["account"])
        self.assertEqual(self.api("beta", "/api/paper-catalog", cookie=alpha)["papers"], [])
        self.assertEqual(self.api("beta", "/api/paper-catalog?q=alpha", cookie=beta)["papers"], [])
        self.assertEqual(self.api("beta", "/api/documents", cookie=alpha)["documents"], [])
        self.assertEqual(self.api("beta", "/api/paper-catalog?q=beta", cookie=beta)["papers"][0]["title"], "beta research")
        self.api("beta", "/papers/1/source.pdf", cookie=alpha, expected=404)
        self.assertEqual(self.api("beta", "/papers/1/source.pdf", cookie=beta), b"%PDF-beta")
        self.api("beta", "/api/experiment-detail?id=1", cookie=alpha, expected=401)
        self.api("beta", "/research-versions/1/entries", cookie=alpha, expected=401)
        self.api("beta", "/research-versions/1/file", cookie=alpha, expected=401)
        self.api("beta", "/research-versions/1/entry?path=alpha.txt", cookie=beta, expected=404)
        self.assertEqual(self.api("beta", "/research-versions/1/entry?path=beta.txt", cookie=beta), b"beta")

        username = "local-agent"
        route = self.api("alpha", "/api/ai/invitations", cookie=alpha, data={"username": username, "role": "local"})["registration_path"]
        client = agent.AgentClient("https://alpha.papers.example.org", username, Ed25519PrivateKey.generate())
        registration = {"public_key": agent.encode(client.private_key.public_key().public_bytes_raw()),
                        "signature": client.sign("register", username, route)}
        self.api("beta", route, data=registration, expected=400)
        self.api("alpha", route, data=registration)
        challenge = self.api("alpha", "/api/ai/challenge", data={"username": username})["challenge"]
        token = self.api("alpha", "/api/ai/login", data={"username": username, "challenge": challenge,
                         "signature": client.sign("login", username, challenge)})["access_token"]
        self.api("alpha", "/api/ai/heartbeat", key=token, data={})
        self.api("beta", "/api/ai/heartbeat", key=token, data={}, expected=401)
        self.assertEqual(self.api("beta", "/api/paper-catalog", key=token)["papers"], [])
        self.api("beta", "/research-versions/1/file", key=token, expected=401)

    def test_revoking_a_human_cancels_pending_invitations_in_that_workspace(self):
        database, alpha = self.labs["alpha"]
        with library.connect(database) as db:
            key = accounts.create_key(db, 1, "Workstation")
        invitation = self.api("alpha", "/api/human-invitations", cookie=alpha, data={
            "email": "colleague@example.org", "role": "member",
        })["invitation_url"].split("=", 1)[1]
        route = self.api("alpha", "/api/ai/invitations", cookie=alpha, data={
            "username": "local-agent", "role": "local",
        })["registration_path"]
        with library.connect(database) as db:
            accounts.revoke_human(db, "researcher")
            self.assertIsNotNone(db.execute("SELECT id FROM accounts WHERE id=1").fetchone())
        for credential in ({"cookie": alpha}, {"key": key}):
            self.assertIsNone(self.api("alpha", "/api/account", **credential)["account"])
        self.api("alpha", "/api/sign-in", data={"username": "researcher", "password": "test only password"}, expected=400)
        self.api("alpha", "/api/register", data={
            "username": "colleague", "email": "colleague@example.org", "display_name": "Colleague",
            "password": "one-time enrollment password", "invite": invitation,
        }, expected=400)
        client = agent.AgentClient("https://alpha.papers.example.org", "local-agent", Ed25519PrivateKey.generate())
        self.api("alpha", route, data={
            "public_key": agent.encode(client.private_key.public_key().public_bytes_raw()),
            "signature": client.sign("register", "local-agent", route),
        }, expected=400)
        self.assertEqual(self.api("beta", "/api/account", cookie=self.labs["beta"][1])["account"]["username"], "researcher")

    def test_pdf_and_artifact_uploads_share_a_quota(self):
        for lab, (_database, admin) in self.labs.items():
            self.api(lab, "/api/experiments", cookie=admin, data={"title": "Experiment"})
        alpha = self.labs["alpha"][1]
        content = b"%PDF-quota"
        pdf_headers = {"Content-Type": "application/pdf", "X-Paper-Filename": "methods.pdf"}
        with patch("paper_app.pdf.extract_pdf", return_value=([], False)):
            self.api("alpha", "/api/papers", cookie=alpha, binary=content, headers=pdf_headers, storage_limit=20)
            self.api("alpha", "/api/papers", cookie=alpha, binary=content, headers=pdf_headers, storage_limit=20)
        # PDFs imported before size tracking still count.
        with library.connect(self.labs["alpha"][0]) as db:
            db.execute("UPDATE papers SET pdf_size=NULL")
        artifact_headers = {
            "Content-Type": "application/octet-stream",
            "X-Research-Metadata": quote(json.dumps({
                "experiment_id": 1, "kind": "data", "title": "Run output", "filename": "result.txt",
            })),
        }

        def upload(_):
            return request(self.labs["alpha"][0], "/api/research-upload", cookie=alpha, binary=b"12345678",
                           headers=artifact_headers, storage_limit=20)[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(upload, range(2))), [200, 413])
        self.assertEqual(len(self.api("alpha", "/api/experiment-detail?id=1", cookie=alpha)["items"]), 1)
        with patch("paper_app.pdf.extract_pdf", return_value=([], False)):
            self.api("alpha", "/api/papers", cookie=alpha, binary=b"%PDF-new", headers=pdf_headers,
                     storage_limit=20, expected=413)
        self.api("beta", "/api/research-upload", cookie=self.labs["beta"][1], binary=b"12345678",
                 headers=artifact_headers, storage_limit=20)
