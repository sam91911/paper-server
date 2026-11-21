"""Create and restore verified, portable library backups.

Usage: python -m paper_app.backup create DATABASE BACKUP_DIRECTORY
       python -m paper_app.backup restore BACKUP_DIRECTORY NEW_DATABASE
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create(database, destination):
    database = database.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists():
        raise ValueError('Backup destination already exists.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # All PDF imports hold a SQLite write transaction while publishing files.
    # Holding a reserved lock prevents imports and other changes while a separate
    # connection copies the database and its referenced files.
    with tempfile.TemporaryDirectory(prefix='.paper-backup-', dir=destination.parent) as temporary:
        root = Path(temporary)
        with sqlite3.connect(database) as lock:
            lock.execute('BEGIN IMMEDIATE')
            source = sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)
            try:
                copy = sqlite3.connect(root / 'library.sqlite3')
                try:
                    source.backup(copy)
                    rows = copy.execute('SELECT id,path,sha256 FROM papers WHERE sha256 IS NOT NULL').fetchall()
                finally:
                    copy.close()
                records = []
                for paper_id, path, expected in rows:
                    original = Path(path)
                    if digest(original) != expected:
                        raise ValueError(f'PDF integrity check failed for paper {paper_id}.')
                    relative = Path('pdfs') / expected / original.name
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, target)
                    if digest(target) != expected:
                        raise ValueError(f'Backup copy failed verification for paper {paper_id}.')
                    records.append({'paper_id': paper_id, 'file': relative.as_posix(), 'sha256': expected})
                manifest = {'version': 1, 'database_sha256': digest(root / 'library.sqlite3'), 'pdfs': records}
                (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
                root.rename(destination)
            finally:
                source.close()
                lock.rollback()


def restore(backup, database):
    backup = backup.resolve(strict=True)
    database = database.absolute()
    pdf_dir = database.with_name(database.name + '.pdfs')
    if database.exists() or pdf_dir.exists():
        raise ValueError('Restore requires a new database and PDF directory.')
    manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    source_db = backup / 'library.sqlite3'
    if manifest.get('version') != 1 or digest(source_db) != manifest.get('database_sha256'):
        raise ValueError('Backup database integrity check failed.')
    entries = manifest['pdfs']
    for entry in entries:
        relative = Path(entry['file'])
        if relative.is_absolute() or '..' in relative.parts or len(relative.parts) != 3 or relative.parts[:2] != ('pdfs', entry['sha256']):
            raise ValueError('Invalid backup PDF path.')
        if digest(backup / relative) != entry['sha256']:
            raise ValueError(f"Backup PDF integrity check failed for paper {entry['paper_id']}.")
    database.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.paper-restore-', dir=database.parent) as temporary:
        root = Path(temporary)
        staged_db = root / 'library.sqlite3'
        staged_pdfs = root / 'pdfs'
        staged_pdfs.mkdir()
        shutil.copyfile(source_db, staged_db)
        staged_db.chmod(0o600)
        staged_pdfs.chmod(0o700)
        with sqlite3.connect(staged_db) as db:
            rows = db.execute('SELECT id,path,sha256 FROM papers WHERE sha256 IS NOT NULL').fetchall()
            if {(r[0], r[2]) for r in rows} != {(e['paper_id'], e['sha256']) for e in entries} or len(rows) != len(entries):
                raise ValueError('Backup manifest does not match the database.')
            old_paths = {row[0]: row[1] for row in rows}
            for entry in entries:
                relative = Path(entry['file'])
                target = staged_pdfs / relative.parts[1] / relative.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.parent.chmod(0o700)
                shutil.copyfile(backup / relative, target)
                target.chmod(0o600)
                final = str(pdf_dir / relative.parts[1] / relative.name)
                db.execute('UPDATE papers SET path=? WHERE id=?', (final, entry['paper_id']))
                db.execute('UPDATE paper_paths SET path=? WHERE paper_id=? AND path=?',
                           (final, entry['paper_id'], old_paths[entry['paper_id']]))
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Restored database failed integrity checks.')
        # Publish the database last, so it is never visible before its PDFs.
        staged_pdfs.rename(pdf_dir)
        try:
            staged_db.rename(database)
        except Exception:
            shutil.rmtree(pdf_dir)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('create', 'restore'))
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        (create if args.operation == 'create' else restore)(args.source, args.destination)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f'Backup: {error}\n')
    print(f'{args.operation.title()} completed: {args.destination}')


if __name__ == '__main__':
    main()
