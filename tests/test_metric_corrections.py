import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from paper_app import accounts, library, pdf
from test_skill_api import request


class MetricCorrectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "library.sqlite3"
        library.initialize(self.database)
        with library.connect(self.database) as db:
            for username, role in (("owner", "user"), ("reader", "member"), ("reviewer-ai", "local"),
                                   ("cloud-agent", "cloud")):
                db.execute("INSERT INTO accounts(username,password_hash,salt,role,ai_location,trusted) VALUES (?,?,?,?,?,?)",
                           (username, b"hash", b"salt", *accounts.role_fields(role), int(role == "user")))
            self.cookie = accounts.start_session(db, 1, None)
            self.reader = accounts.create_key(db, 2, "reader")
            self.ai = accounts.create_key(db, 3, "local")
            self.cloud = accounts.create_key(db, 4, "cloud")
            self.source = self.database.parent / "source.pdf"
            self.rows = ((1, "power", "10", "W", "test", "source text"), (2, "power", "20", "W", "", ""))
            self.paper = library.store(db, self.source, self.rows)
            db.execute("INSERT INTO paper_access VALUES (?,1,'owner')", (self.paper,))
            db.executemany("INSERT INTO item_grants VALUES ('paper',?,?)", ((self.paper, 2), (self.paper, 3)))

    def api(self, path, *, status=200, **options):
        result, body = request(self.database, path, **options)
        self.assertEqual(result, status, body)
        return body

    def list_rows(self, **credentials):
        return self.api(f"/api/paper-metrics?paper_id={self.paper}", **credentials)["metrics"]

    def grant(self, metric_id, username, action="grant", **credentials):
        return self.api("/api/metric-editors", data={"metric_id": metric_id, "username": username, "action": action},
                        **credentials)

    def correction(self, row, **changes):
        data = {field: row[field] for field in ("revision", "page", "metric", "value", "unit", "conditions", "evidence")}
        return {"metric_id": row["id"], **data, "value": "12.5", "reason": "Verified Table II.", **changes}

    def test_named_grants_apply_only_to_one_metric_with_paper_access(self):
        first, second = self.list_rows(cookie=self.cookie)
        self.assertTrue(first["can_edit"])
        self.assertFalse(self.list_rows(key=self.ai)[0]["can_edit"])
        self.api("/api/paper-metrics", key=self.ai, data=self.correction(first), status=403)
        self.grant(first["id"], "reviewer-ai", key=self.ai, status=403)
        self.grant(first["id"], "reviewer-ai", cookie=self.cookie)
        self.grant(second["id"], "reader", cookie=self.cookie)
        self.grant(first["id"], "cloud-agent", cookie=self.cookie)
        self.assertEqual([row["can_edit"] for row in self.list_rows(key=self.ai)], [True, False])
        self.assertEqual([row["can_edit"] for row in self.list_rows(key=self.reader)], [False, True])
        self.api("/api/paper-metrics", key=self.ai, data=self.correction(second), status=403)
        self.api("/api/paper-metrics", key=self.cloud, data=self.correction(first), status=403)

        self.assertEqual(self.api("/api/paper-metrics", key=self.ai, data=self.correction(first))["revision"], 2)
        self.assertEqual(self.api("/api/paper-metrics", key=self.reader, data=self.correction(second))["revision"], 2)
        self.api("/api/paper-metrics", cookie=self.cookie, data=self.correction(first), status=409)
        self.grant(first["id"], "reviewer-ai", "revoke", cookie=self.cookie)
        self.api("/api/paper-metrics", key=self.ai, data=self.correction(first, revision=2), status=403)

        history = f"/api/metric-history?metric_id={first['id']}"
        self.assertEqual(self.api(history, cookie=self.cookie)["editors"], ["cloud-agent"])
        self.assertNotIn("editors", self.api(history, key=self.ai))
        self.api(history, key=self.cloud, status=404)
        self.api("/api/paper-access", cookie=self.cookie, data={
            "paper_id": self.paper, "audience": "owner", "recipients": ["reviewer-ai"]})
        self.api("/api/paper-metrics", key=self.reader, data=self.correction(second, revision=2), status=403)

    def test_compare_and_export_use_corrections_and_keep_original(self):
        first, _ = self.list_rows(cookie=self.cookie)
        self.api("/api/paper-metrics", cookie=self.cookie, data=self.correction(first, value="Infinity"), status=400)
        self.api("/api/paper-metrics", cookie=self.cookie, data=self.correction(first, reason=" "), status=400)
        self.api("/api/paper-metrics", cookie=self.cookie, data=self.correction(first, page=3))
        # Re-importing the extracted values keeps the correction and its stable ID.
        with library.connect(self.database) as db:
            library.store(db, self.source, self.rows)
        updated, _ = self.list_rows(cookie=self.cookie)
        self.assertEqual((updated["id"], updated["revision"]), (first["id"], 2))
        for route in ("/api/compare", "/api/metric-page"):
            self.assertIn((3, "12.5"), [(row["page"], row["value"]) for row in self.api(route, cookie=self.cookie)["metrics"]])
        csv = self.api("/exports/metrics.csv", cookie=self.cookie).decode("utf-8-sig")
        self.assertIn(",3,power,12.5,W,test,source text", csv)
        history = self.api(f"/api/metric-history?metric_id={first['id']}", cookie=self.cookie)
        self.assertEqual(history["original"]["value"], "10")
        self.assertEqual(history["corrections"][0]["editor"], "owner")
        self.assertEqual(history["corrections"][0]["reason"], "Verified Table II.")

    def test_claimed_csv_paper_can_attach_its_pdf_without_losing_access(self):
        with library.connect(self.database) as db:
            db.execute("DELETE FROM item_grants")
            db.execute("DELETE FROM paper_access")
        self.api("/api/claim-paper", key=self.ai, data={"paper_id": self.paper}, status=403)
        self.api("/api/claim-paper", cookie=self.cookie, data={"paper_id": self.paper})
        self.api("/api/claim-paper", cookie=self.cookie, data={"paper_id": self.paper}, status=403)
        first, _ = self.list_rows(cookie=self.cookie)
        self.api("/api/paper-access", cookie=self.cookie, data={
            "paper_id": self.paper, "audience": "users", "recipients": ["reviewer-ai"]})
        self.grant(first["id"], "reviewer-ai", cookie=self.cookie)
        self.source.write_bytes(b"%PDF-source")
        with patch.object(pdf, "extract_pdf", return_value=(self.rows, True)):
            result = pdf.import_pdf(self.database, self.source.name, self.source.read_bytes(),
                                    {"id": 1, "role": "user"}, "owner")
        self.assertEqual(result["paper_id"], self.paper)
        self.assertTrue(self.list_rows(key=self.ai)[0]["can_edit"])

    def test_partial_correction_preserves_long_existing_evidence(self):
        evidence = "source " * 8_000
        with library.connect(self.database) as db:
            library.store(db, self.source, ((3, "power", "30", "W", "", evidence),))
        row = self.list_rows(cookie=self.cookie)[-1]
        data = {"metric_id": row["id"], "revision": row["revision"], "reason": "Verified source.", "value": "31"}
        self.api("/api/paper-metrics", cookie=self.cookie, data=data)
        current = self.list_rows(cookie=self.cookie)[-1]
        self.assertEqual((current["value"], current["evidence"]), ("31", evidence))
        self.api("/api/paper-metrics", cookie=self.cookie, data={**data, "revision": 2}, status=400)

    def test_removed_metric_stays_out_of_comparison_and_can_be_restored(self):
        first, second = self.list_rows(cookie=self.cookie)
        remove = {"metric_id": first["id"], "revision": 1, "action": "remove", "reason": "Cited prior work."}
        self.api("/api/paper-metrics", key=self.ai, data=remove, status=403)
        self.grant(first["id"], "reviewer-ai", cookie=self.cookie)
        self.assertTrue(self.api("/api/paper-metrics", key=self.ai, data=remove)["removed"])
        self.api("/api/paper-metrics", key=self.ai, data=remove, status=409)
        self.assertEqual([row["id"] for row in self.list_rows(cookie=self.cookie)], [second["id"]])
        removed_path = f"/api/paper-metrics?paper_id={self.paper}&removed=1"
        removed = self.api(removed_path, key=self.ai)["metrics"][0]
        self.assertEqual((removed["id"], removed["revision"], removed["removed"]), (first["id"], 2, True))
        for route in ("/api/compare", "/api/metric-page"):
            self.assertEqual([row["value"] for row in self.api(route, cookie=self.cookie)["metrics"]], ["20"])
        self.assertNotIn(",1,power,10,W,", self.api("/exports/metrics.csv", cookie=self.cookie).decode("utf-8-sig"))
        restore = {**remove, "revision": 2, "action": "restore", "reason": "Verified the paper's results."}
        self.assertFalse(self.api("/api/paper-metrics", key=self.ai, data=restore)["removed"])
        self.assertEqual([row["value"] for row in self.list_rows(cookie=self.cookie)], ["10", "20"])
        history = self.api(f"/api/metric-history?metric_id={first['id']}", cookie=self.cookie)
        self.assertEqual([item["removed"] for item in history["corrections"]], [False, True])

    def test_sqlite_upgrade_preserves_legacy_rowids(self):
        database = self.database.parent / "old.sqlite3"
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript(library.SCHEMA)
            db.execute("DROP TABLE metrics")
            db.execute("CREATE TABLE metrics(paper_id REFERENCES papers(id),page,metric,value,unit,conditions,evidence)")
            db.execute("INSERT INTO papers(id,path) VALUES (1,'legacy.pdf')")
            db.execute("INSERT INTO metrics(rowid,paper_id,page,metric,value,unit,conditions,evidence) VALUES (17,1,1,'power','10','W','','')")
        library.initialize(database)
        with library.connect(database) as db:
            self.assertEqual(tuple(db.execute("SELECT cursor_id,value FROM metrics").fetchone()), (17, "10"))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
