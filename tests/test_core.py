import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_app import accounts, library, pdf, sharing


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'library.sqlite3'
        library.initialize(self.path)
        with library.connect(self.path) as db:
            for username, role in [('owner', 'user'), ('reader', 'member'), ('local', 'local'), ('cloud', 'cloud')]:
                # Authentication itself is tested separately; avoid expensive password hashing in fixtures.
                db.execute('INSERT INTO accounts(username,password_hash,salt,role,ai_location,trusted) VALUES (?,?,?,?,?,?)',
                           (username, b'hash', b'salt', *accounts.role_fields(role), role == 'user'))
            self.users = {row['username']: {'id': row['id'], 'username': row['username'], 'role': row['effective_role']}
                          for row in db.execute(f"SELECT a.*, {accounts.ROLE_SQL.format(alias='a')} effective_role FROM accounts a")}

    def test_document_visibility_and_revision_conflict(self):
        with library.connect(self.path) as db:
            owner, reader = self.users['owner'], self.users['reader']
            doc = sharing.save_document(db, owner, {'title': 'Note', 'markdown': 'text', 'recipients': ['reader']})
            self.assertIsNotNone(sharing.document_for(db, reader, doc))
            self.assertIsNone(sharing.document_for(db, self.users['cloud'], doc))
            sharing.save_document(db, owner, {'document_id': doc, 'title': 'Changed', 'markdown': 'text', 'revision': 1, 'recipients': []})
            with self.assertRaises(sharing.EditConflict):
                sharing.save_document(db, owner, {'document_id': doc, 'title': 'Stale', 'markdown': '', 'revision': 1})
            self.assertIsNone(sharing.document_for(db, reader, doc))

    def test_paper_audience_and_direct_grant(self):
        with library.connect(self.path) as db:
            paper = library.store(db, '/tmp/example.pdf', ())
            db.execute('INSERT INTO paper_access VALUES (?,?,?)', (paper, self.users['owner']['id'], 'local'))
            sharing.set_recipients(db, 'paper', paper, ['reader'])
            for name in ('owner', 'reader', 'local'):
                self.assertEqual(sharing.paper_for(db, paper, self.users[name])['id'], paper)
            with self.assertRaises(sharing.AccessDenied):
                sharing.paper_for(db, paper, self.users['cloud'])
            sharing.set_recipients(db, 'paper', paper, [])
            with self.assertRaises(sharing.AccessDenied):
                sharing.paper_for(db, paper, self.users['reader'])

    def test_thread_visibility_respects_parent_and_target(self):
        with library.connect(self.path) as db:
            owner, reader = self.users['owner'], self.users['reader']
            paper = library.store(db, '/tmp/thread.pdf', ())
            db.execute('INSERT INTO paper_access VALUES (?,?,?)', (paper, owner['id'], 'all'))
            sharing.set_recipients(db, 'paper', paper, ['reader'])
            hidden = library.save_comment(db, paper, 'private parent', owner, audience='owner')
            library.save_comment(db, paper, 'public child', owner, parent_id=hidden, audience='all')
            visible = library.save_comment(db, paper, 'shared parent', owner, audience='all', recipients=['reader'])
            target = sharing.save_document(db, owner, {'title': 'Private', 'markdown': 'line'})
            library.save_comment(db, paper, 'private anchor', owner, audience='all',
                                 location={'kind': 'document', 'id': target, 'position': 1})
            comments = library.comment_snapshot(db, reader)
            self.assertEqual([c['id'] for c in comments], [visible])
            self.assertFalse(library.can_reply(db, paper, hidden, reader))
            self.assertTrue(library.can_reply(db, paper, visible, reader))
            with self.assertRaises(accounts.CommentAccessDenied):
                library.save_comment(db, paper, 'unauthorized edit', reader, comment_id=visible)

    def test_comment_audience_changes_hide_descendants(self):
        with library.connect(self.path) as db:
            owner, reader = self.users['owner'], self.users['reader']
            paper = library.store(db, '/tmp/thread2.pdf', ())
            db.execute('INSERT INTO paper_access VALUES (?,?,?)', (paper, owner['id'], 'all'))
            sharing.set_recipients(db, 'paper', paper, ['reader'])
            parent = library.save_comment(db, paper, 'parent', owner, audience='all', recipients=['reader'])
            child = library.save_comment(db, paper, 'child', reader, parent_id=parent, audience='owner')
            self.assertEqual({c['id'] for c in library.comment_snapshot(db, reader)}, {parent, child})
            library.save_comment(db, paper, 'parent', owner, comment_id=parent, audience='owner', recipients=[])
            self.assertEqual(library.comment_snapshot(db, reader), [])

    def test_csv_validation_and_spreadsheet_escaping(self):
        with library.connect(self.path) as db:
            with self.assertRaises(ValueError):
                library.import_csv(db, io.StringIO('wrong,columns\na,b\n'), Path('/tmp'))
        for value in ('=1+1', '+SUM(A1)', '-2', '@cmd', '\tformula'):
            self.assertTrue(pdf.spreadsheet_text(value).startswith("'"))
        self.assertEqual(pdf.spreadsheet_text('normal'), 'normal')

    def test_initialize_is_idempotent(self):
        library.initialize(self.path)
        with library.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0], 4)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_legacy_comment_migration_preserves_authors_and_replies(self):
        import sqlite3
        with library.connect(self.path) as db:
            paper = library.store(db, '/tmp/legacy.pdf', ())
            parent = library.save_comment(db, paper, 'parent', self.users['owner'], audience='all')
            child = library.save_comment(db, paper, 'reply', self.users['owner'], parent_id=parent, audience='owner')
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute('ALTER TABLE comments RENAME TO current_comments')
            db.execute("""CREATE TABLE comments (
                id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id), body TEXT NOT NULL,
                updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, parent_id INTEGER REFERENCES comments(id),
                audience TEXT, deleted INTEGER DEFAULT 0, doi_refs TEXT DEFAULT '[]',
                target_kind TEXT, target_id INTEGER, target_position INTEGER)""")
            columns = ','.join(library.COMMENT_COLUMNS)
            db.execute(f'INSERT INTO comments({columns}) SELECT {columns} FROM current_comments')
            db.execute('DROP TABLE current_comments')
            # Simulate legacy FK definitions, rather than ALTER TABLE's automatic rewrite.
            db.execute('DROP TABLE comment_authors')
            db.execute("CREATE TABLE comment_authors (comment_id INTEGER PRIMARY KEY REFERENCES comments(id) ON DELETE CASCADE, account_id INTEGER NOT NULL REFERENCES accounts(id), kind TEXT NOT NULL)")
            db.executemany('INSERT INTO comment_authors VALUES (?,?,?)', [(parent, self.users['owner']['id'], 'user'), (child, self.users['owner']['id'], 'user')])
        library.initialize(self.path)
        with library.connect(self.path) as db:
            comments = db.execute('SELECT id,parent_id,body,document_id FROM comments ORDER BY id').fetchall()
            self.assertEqual([(r['id'], r['parent_id'], r['body'], r['document_id']) for r in comments],
                             [(parent, None, 'parent', None), (child, parent, 'reply', None)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM comment_authors').fetchone()[0], 2)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_integrity_reports_missing_changed_and_orphan_files(self):
        from paper_app import integrity
        import hashlib
        directory = self.path.with_name(self.path.name + '.pdfs') / 'files'
        directory.mkdir(parents=True)
        changed = directory / 'changed.pdf'
        changed.write_bytes(b'changed')
        orphan = directory / 'orphan.pdf'
        orphan.write_bytes(b'orphan')
        with library.connect(self.path) as db:
            db.execute('INSERT INTO papers(path,sha256) VALUES (?,?)',
                       (str(changed), hashlib.sha256(b'original').hexdigest()))
            db.execute('INSERT INTO papers(path,sha256) VALUES (?,?)',
                       (str(directory / 'missing.pdf'), hashlib.sha256(b'missing').hexdigest()))
        result = integrity.check(self.path)
        self.assertTrue(result['database_ok'])
        self.assertEqual(len(result['missing']), 1)
        self.assertEqual(len(result['changed']), 1)
        self.assertEqual(result['orphans'], [str(orphan)])
        self.assertTrue(orphan.exists())

    @patch('paper_app.pdf.extract_pdf', return_value=({}, True))
    def test_pdf_import_failure_does_not_leave_file(self, _extract):
        with patch('paper_app.pdf.library.store', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                pdf.import_pdf(self.path, 'test.pdf', b'%PDF-sample', self.users['owner'], 'owner')
        directory = self.path.with_name(self.path.name + '.pdfs')
        self.assertFalse(any(directory.rglob('*.pdf')))

    @patch('paper_app.pdf.extract_pdf', return_value=({}, True))
    def test_repeat_import_keeps_original_access(self, _extract):
        payload = b'%PDF-same'
        first = pdf.import_pdf(self.path, 'first.pdf', payload, self.users['owner'], 'owner')
        second = pdf.import_pdf(self.path, 'second.pdf', payload, self.users['owner'], 'all')
        self.assertEqual(first['paper_id'], second['paper_id'])
        with library.connect(self.path) as db:
            paper = db.execute('SELECT path FROM papers WHERE id=?', (first['paper_id'],)).fetchone()
            self.assertEqual(Path(paper['path']).read_bytes(), payload)
            self.assertEqual(db.execute('SELECT audience FROM paper_access WHERE paper_id=?', (first['paper_id'],)).fetchone()[0], 'owner')
        with self.assertRaises(sharing.AccessDenied):
            pdf.import_pdf(self.path, 'other.pdf', payload, self.users['cloud'], 'owner')



class BackupTests(unittest.TestCase):
    def test_backup_restore_and_tamper_detection(self):
        from paper_app import backup
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dbfile = root / 'original.sqlite3'
            library.initialize(dbfile)
            payload = b'%PDF-backup test'
            with library.connect(dbfile) as db:
                db.execute("INSERT INTO accounts(username,password_hash,salt) VALUES ('owner',?,?)", (b'h', b's'))
                owner = {'id': 1, 'role': 'user', 'username': 'owner'}
            with patch('paper_app.pdf.extract_pdf', return_value=({}, True)):
                pdf.import_pdf(dbfile, 'test.pdf', payload, owner, 'owner')
            archive = root / 'backup'
            backup.create(dbfile, archive)
            restored = root / 'restored.sqlite3'
            backup.restore(archive, restored)
            with library.connect(restored) as db:
                paper = db.execute('SELECT path,sha256 FROM papers').fetchone()
                self.assertEqual(Path(paper['path']).read_bytes(), payload)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            next((archive / 'pdfs').rglob('*.pdf')).write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                backup.restore(archive, root / 'bad.sqlite3')
            self.assertFalse((root / 'bad.sqlite3').exists())

    def test_restored_library_can_authenticate_and_read_items(self):
        from paper_app import backup
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'library.sqlite3'
            library.initialize(original)
            with library.connect(original) as db:
                accounts.create_account(db, 'reviewer', 'a long password 123', 'user')
                account = accounts.authenticate(db, 'reviewer', 'a long password 123')
                document = sharing.save_document(db, account, {'title': 'Restored note', 'markdown': 'content'})
            backup.create(original, root / 'archive')
            restored = root / 'restored.sqlite3'
            backup.restore(root / 'archive', restored)
            with library.connect(restored) as db:
                account = accounts.authenticate(db, 'reviewer', 'a long password 123')
                self.assertEqual(sharing.document_for(db, account, document)['markdown'], 'content')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_backup_blocks_concurrent_writes_while_copying(self):
        from paper_app import backup
        import sqlite3
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dbfile = root / 'original.sqlite3'
            library.initialize(dbfile)
            with library.connect(dbfile) as db:
                db.execute("INSERT INTO accounts(username,password_hash,salt) VALUES ('owner',?,?)", (b'h', b's'))
                owner = {'id': 1, 'role': 'user', 'username': 'owner'}
            with patch('paper_app.pdf.extract_pdf', return_value=({}, True)):
                pdf.import_pdf(dbfile, 'test.pdf', b'%PDF-concurrency', owner, 'owner')
            actual_copy = shutil.copyfile
            attempted = []
            def copy_while_writing(source, target, *args, **kwargs):
                with sqlite3.connect(dbfile, timeout=0) as competing:
                    with self.assertRaises(sqlite3.OperationalError):
                        competing.execute("INSERT INTO groups(name) VALUES ('during backup')")
                attempted.append(True)
                return actual_copy(source, target, *args, **kwargs)
            with patch('paper_app.backup.shutil.copyfile', side_effect=copy_while_writing):
                backup.create(dbfile, root / 'backup')
            self.assertTrue(attempted)
            with library.connect(dbfile) as db:
                db.execute("INSERT INTO groups(name) VALUES ('after backup')")

    def test_backup_failure_never_publishes_partial_directory(self):
        from paper_app import backup
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dbfile = root / 'original.sqlite3'
            library.initialize(dbfile)
            with library.connect(dbfile) as db:
                db.execute("INSERT INTO papers(path,sha256) VALUES (?,?)", (str(root / 'missing.pdf'), 'a' * 64))
            with self.assertRaises(OSError):
                backup.create(dbfile, root / 'backup')
            self.assertFalse((root / 'backup').exists())
            self.assertFalse(list(root.glob('.paper-backup-*')))


if __name__ == '__main__':
    unittest.main()
