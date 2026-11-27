import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_app import library, metadata_sync


class MetadataQueueTests(unittest.TestCase):
    def test_queue_prioritizes_due_work_and_skips_ineligible_papers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.sqlite3"
            library.initialize(path)
            with library.connect(path) as db:
                for i in range(1, 10):
                    db.execute("INSERT INTO papers(id,path) VALUES (?,?)", (i, f"/tmp/paper-{i}.pdf"))
                db.execute("UPDATE papers SET doi='10.1234/example' WHERE id IN (2,4,8,9)")
                db.execute("UPDATE papers SET sha256='digest-' || id WHERE id IN (3,4,5,7)")
                db.execute("INSERT INTO archived_papers VALUES (4)")
                db.executemany("INSERT INTO paper_metadata_checks VALUES (?,?,?,?)", (
                    (5, 0, 10, ""), (6, 1, 20, None), (7, 0, 25, None),
                    (8, 0, 100, None), (9, 0, 30, None),
                ))
                self.assertEqual([paper["id"] for paper in metadata_sync.pending(db, 90)], [2, 3, 6, 7, 9])
                db.execute("DELETE FROM archived_papers WHERE paper_id=4")
                self.assertEqual([paper["id"] for paper in metadata_sync.pending(db, 100)], [2, 3, 4, 6, 7, 9, 8])

    def test_idle_worker_backs_off_and_returns_to_normal_after_work(self):
        class Stop:
            def __init__(self):
                self.waits = []

            def is_set(self):
                return False

            def wait(self, delay):
                self.waits.append(delay)
                return len(self.waits) == 5

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.sqlite3"
            library.initialize(path)
            stop = Stop()
            with patch.object(metadata_sync, "pending", side_effect=[[], [], [], [{"id": 1}]]), \
                    patch.object(metadata_sync, "check_paper") as check:
                metadata_sync.run(path, stop)
            self.assertEqual(stop.waits, [30, 60, 120, 1, 30])
            check.assert_called_once_with(path, {"id": 1})
