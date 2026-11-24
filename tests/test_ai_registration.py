import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_app import accounts, library
from paper_client import agent, review
from test_skill_api import request


class AIRegistrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "library.sqlite3"
        library.initialize(self.database)
        with library.connect(self.database) as db:
            accounts.create_account(db, "owner", "owner password", "user")
            self.owner = accounts.create_key(db, 1, "owner")

    def api(self, path, *, expected=200, **options):
        status, result = request(self.database, path, **options)
        self.assertEqual(status, expected, result)
        return result

    def test_enrollment_replay_and_signed_login(self):
        invitation = {"username": "Researcher", "role": "cloud"}
        self.api("/api/ai/invitations", data=invitation, expected=401)
        route = self.api("/api/ai/invitations", key=self.owner, data=invitation)["registration_path"]
        reviewer = agent.AgentClient(8765, "Researcher", Ed25519PrivateKey.generate())
        body = {"public_key": agent.encode(reviewer.private_key.public_key().public_bytes_raw()),
                "signature": reviewer.sign("register", "Researcher", route)}
        self.api(route, data={**body, "signature": reviewer.sign("register", "AnotherName", route)}, expected=401)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: request(self.database, route, data=body), range(2)))
        self.assertEqual(sorted(status for status, _ in responses), [200, 400])
        challenge = self.api("/api/ai/challenge", data={"username": "researcher"})
        value = challenge["challenge"]
        login = {"username": "researcher", "challenge": value,
                 "signature": reviewer.sign("login", challenge["username"], value)}
        self.api("/api/ai/login", data={**login, "signature": reviewer.sign("login", "Researcher", "other")}, expected=401)
        token = self.api("/api/ai/login", data=login)["access_token"]
        self.api("/api/ai/login", data=login, expected=401)
        self.assertEqual(self.api("/api/account", key=token)["account"]["role"], "cloud")
        self.assertIsNone(self.api("/api/account", cookie=token.removeprefix(accounts.AI_SESSION_PREFIX))["account"])
        self.api("/api/ai/invitations", key=token, data=invitation, expected=403)
        with library.connect(self.database) as db:
            db.execute("UPDATE sessions SET expires=0 WHERE token_hash=?", (accounts.token_hash(token),))
        self.assertIsNone(self.api("/api/account", key=token)["account"])
        with library.connect(self.database) as db:
            accounts.set_role(db, "Researcher", "member")
        self.api("/api/ai/challenge", data={"username": "Researcher"}, expected=401)

    def test_client_persists_key_and_renews_access(self):
        identity = self.database.parent / ".paper-library" / "reviewer.json"
        expired = self.api("/api/ai/invitations", key=self.owner, data={"username": "reviewer", "role": "local"})
        with library.connect(self.database) as db:
            db.execute("UPDATE ai_invites SET expires=0")
        active = self.api("/api/ai/invitations", key=self.owner, data={"username": "reviewer", "role": "local"})

        def send(client, route, data=None, **_):
            status, result = request(self.database, route, key=client.key, data=data)
            if status != 200:
                raise review.LibraryError(result["error"], status)
            return json.dumps(result).encode()

        with patch.object(agent.LibraryClient, "request", send):
            with self.assertRaisesRegex(ValueError, "expired"):
                agent.register(identity, "reviewer", "http://127.0.0.1:8765" + expired["registration_path"])
            saved = identity.read_bytes()
            enrolled = agent.register(identity, "reviewer", "http://127.0.0.1:8765" + active["registration_path"])
            self.assertEqual(enrolled["role"], "local")
            self.assertEqual(identity.read_bytes(), saved)
            client = agent.AgentClient.from_identity(identity)
            client.require_role("local")
            first_token = client.key
            client.renew_at = 0
            self.assertIn("skill", client.get_json("/api/skills/default"))
            self.assertNotEqual(first_token, client.key)
        if os.name == "posix":
            self.assertEqual(identity.stat().st_mode & 0o777, 0o600)

    def test_operator_can_cancel_replace_and_rotate_without_changing_account(self):
        route = "/api/ai/invitations"
        with library.connect(self.database) as db:
            account_id = accounts.create_account(db, "another", "other password", "user")
            other = accounts.create_key(db, account_id, "operator")
        enrollment = self.api(route, key=self.owner, data={"username": "Reviewer", "role": "local"})
        old = agent.AgentClient(8765, "Reviewer", Ed25519PrivateKey.generate())

        def register(client, invite, expected=200):
            path = invite["registration_path"]
            return self.api(path, expected=expected, data={
                "public_key": agent.encode(client.private_key.public_key().public_bytes_raw()),
                "signature": client.sign("register", "Reviewer", path),
            })

        def login_body(client):
            challenge = self.api("/api/ai/challenge", data={"username": "reviewer"})["challenge"]
            return {"username": "reviewer", "challenge": challenge,
                    "signature": client.sign("login", "Reviewer", challenge)}

        self.api(route, key=other, data={"action": "cancel", "invite_id": enrollment["invite_id"]}, expected=404)
        self.api(route, key=self.owner, data={"action": "cancel", "invite_id": enrollment["invite_id"]})
        register(old, enrollment, expected=400)
        replacement = self.api(route, key=self.owner, data={"action": "replace", "invite_id": enrollment["invite_id"]})
        original = register(old, replacement)["account"]
        token = self.api("/api/ai/login", data=login_body(old))["access_token"]
        document = self.api("/api/documents", key=self.owner, data={
            "title": "A shared document", "markdown": "Source", "recipients": ["Reviewer"],
        })["document_id"]
        review_id = self.api("/api/reviews", key=self.owner, data={
            "action": "create", "kind": "document", "target_id": document, "agent": "Reviewer", "agent_role": "local",
        })["review"]["id"]
        self.api("/api/reviews", key=token, data={"action": "complete", "id": review_id, "status": "complete", "response": "Review"})
        pending_challenge = login_body(old)
        self.api(route, key=other, data={"action": "rotate", "username": "Reviewer"}, expected=404)
        rotation = self.api(route, key=self.owner, data={"action": "rotate", "username": "Reviewer"})
        register(old, rotation, expected=400)
        new = agent.AgentClient(8765, "Reviewer", Ed25519PrivateKey.generate())
        self.assertEqual(register(new, rotation)["account"], original)
        self.assertIsNone(self.api("/api/account", key=token)["account"])
        self.api("/api/ai/login", data=pending_challenge, expected=401)
        self.api("/api/ai/login", data=login_body(old), expected=401)
        new_token = self.api("/api/ai/login", data=login_body(new))["access_token"]
        self.assertEqual(self.api(f"/api/reviews?id={review_id}", key=new_token)["review"]["response"], "Review")
        self.assertEqual(self.api(f"/api/document?id={document}", key=new_token)["document"]["title"], "A shared document")
        dashboard = self.api(route, key=self.owner)
        self.assertEqual({row["status"] for row in dashboard["invitations"]}, {"canceled", "used"})
        self.assertIsNotNone(dashboard["agents"][0]["last_authenticated"])
        self.assertEqual(self.api(route, key=other), {"invitations": [], "agents": []})
