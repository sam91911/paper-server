import base64
import tempfile
import unittest
from pathlib import Path

from paper_app import accounts, library
from test_skill_api import request


class AccountProfileTests(unittest.TestCase):
    def test_profiles_are_private_and_can_be_updated_and_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "profile.sqlite3"
            library.initialize(database)
            with library.connect(database) as db:
                owner = accounts.create_account(db, "owner", "test password", "user", email="owner@example.com")
                member = accounts.create_account(db, "member", "test password", "member")
                agent = accounts.create_account(db, "agent", "test password", "local")
                owner_cookie, member_cookie, agent_cookie = (
                    accounts.start_session(db, account, None) for account in (owner, member, agent)
                )
                member_key = accounts.create_key(db, member, "test")

            profile = "/api/account/profile"
            avatar_path = "/api/account/avatar"
            avatar = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jNioAAAAASUVORK5CYII="
            data = {"display_name": "Reader", "email": "Reader@Example.com", "avatar": avatar}
            self.assertEqual(request(database, profile, data=data)[0], 401)
            self.assertEqual(request(database, profile, key=member_key, data=data)[0], 401)
            self.assertEqual(request(database, profile, cookie=agent_cookie, data=data)[0], 403)
            self.assertEqual(request(database, profile, cookie=member_cookie, data=data)[0], 200)
            self.assertEqual(request(database, avatar_path, cookie=member_cookie), (200, base64.b64decode(avatar)))
            self.assertEqual(request(database, avatar_path, cookie=owner_cookie)[0], 404)
            self.assertEqual(request(database, avatar_path)[0], 401)

            _, result = request(database, "/api/account", cookie=member_cookie)
            self.assertEqual(result["account"]["display_name"], "Reader")
            self.assertEqual(result["account"]["email"], "reader@example.com")
            self.assertTrue(result["account"]["has_avatar"])
            self.assertEqual(request(database, profile, cookie=member_cookie, data={"avatar": "not an image"})[0], 400)
            self.assertEqual(request(database, profile, cookie=owner_cookie, data={"email": "invalid"})[0], 400)
            self.assertEqual(request(database, profile, cookie=member_cookie,
                                     data={"display_name": "", "email": "", "avatar": None})[0], 200)
            _, result = request(database, "/api/account", cookie=member_cookie)
            self.assertEqual(result["account"]["display_name"], "")
            self.assertIsNone(result["account"]["email"])
            self.assertFalse(result["account"]["has_avatar"])
            self.assertEqual(request(database, avatar_path, cookie=member_cookie)[0], 404)
