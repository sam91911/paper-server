"""Exercise real WebAuthn verification with a software authenticator fixture."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

from paper_app import accounts, library
from test_skill_api import request


class PasskeyTests(unittest.TestCase):
    def test_existing_account_enrolls_signs_in_and_revokes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "passkeys.sqlite3"
            library.initialize(database)
            with library.connect(database) as db:
                owner = accounts.create_account(db, "owner", "test password for owner", "user")
                session = accounts.start_session(db, owner, None)
                other_session = accounts.start_session(db, owner, None)
            origin = "https://library.example"
            server = {"public_url": origin, "headers": {"Host": "library.example", "Origin": origin}}

            def post(action, data, cookie=None):
                return request(database, f"/api/passkeys/{action}", data=data, cookie=cookie, **server)

            def client_data(kind, options):
                return json.dumps({"type": f"webauthn.{kind}", "challenge": options["challenge"],
                                   "origin": origin, "crossOrigin": False}).encode()

            self.assertEqual(post("register-options", {})[0], 401)
            status, registration = post("register-options", {}, session)
            self.assertEqual(status, 200)
            identifier = b"fixture-credential-id"
            encoded_id = bytes_to_base64url(identifier)
            signing_key = ec.generate_private_key(ec.SECP256R1())
            points = signing_key.public_key().public_numbers()
            cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: points.x.to_bytes(32, "big"), -3: points.y.to_bytes(32, "big")})
            rp_hash = hashlib.sha256(b"library.example").digest()
            attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData":
                rp_hash + b"\x45" + bytes(4) + bytes(16) + len(identifier).to_bytes(2, "big") + identifier + cose})
            credential = {"id": encoded_id, "rawId": encoded_id, "type": "public-key", "response": {
                "clientDataJSON": bytes_to_base64url(client_data("create", registration["options"])),
                "attestationObject": bytes_to_base64url(attestation),
            }}
            attach = {"ceremony": registration["ceremony"], "credential": credential, "label": "Test passkey"}
            self.assertEqual(post("register", attach, other_session)[0], 400)
            self.assertEqual(post("register", attach, session)[0], 200)
            self.assertEqual(post("register", attach, session)[0], 400)

            def signed_login(count):
                status, login = post("login-options", {})
                self.assertEqual(status, 200)
                client = client_data("get", login["options"])
                authenticator = rp_hash + b"\x05" + count.to_bytes(4, "big")
                signature = signing_key.sign(authenticator + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
                return {"ceremony": login["ceremony"], "credential": {
                    "id": encoded_id, "rawId": encoded_id, "type": "public-key", "response": {
                        "clientDataJSON": bytes_to_base64url(client),
                        "authenticatorData": bytes_to_base64url(authenticator),
                        "signature": bytes_to_base64url(signature),
                        "userHandle": registration["options"]["user"]["id"],
                    },
                }}

            login = signed_login(1)
            status, result = post("login", login)
            self.assertEqual(status, 200)
            self.assertEqual(result["account"]["id"], owner)
            self.assertEqual(post("login", login)[0], 400)
            self.assertEqual(post("login", signed_login(1))[0], 400)
            self.assertEqual(post("revoke", {"id": encoded_id}, session)[0], 200)
            self.assertEqual(post("login", signed_login(2))[0], 400)
