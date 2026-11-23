"""Read-only checks for PDF and uploaded research artifact integrity."""
import argparse
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from . import database as storage, library


def bad_artifacts(db):
    if not db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='research_versions'").fetchone():
        return []
    bad = []
    rows = db.execute("SELECT id,sha256,content IS NOT NULL FROM research_versions WHERE sha256 IS NOT NULL OR content IS NOT NULL")
    for version_id, expected, has_content in rows:
        if not expected or not has_content:
            bad.append(version_id)
            continue
        digest = hashlib.sha256()
        with db.blobopen("research_versions", "content", version_id, readonly=True) as content:
            for block in iter(lambda: content.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            bad.append(version_id)
    return bad


def check(database):
    if isinstance(database, storage.PostgreSQL):
        with library.connect(database) as db:
            storage.begin(db)
            rows = db.execute("SELECT id,path,sha256 FROM papers WHERE sha256 IS NOT NULL").fetchall()
            artifacts = [row[0] for row in db.execute(
                "SELECT id FROM research_versions WHERE (sha256 IS NOT NULL OR content IS NOT NULL) "
                "AND (sha256 IS NULL OR content IS NULL OR sha256<>encode(sha256(content),'hex')) ORDER BY id"
            )]
        database_ok = True
    else:
        database = database.resolve(strict=True)
        with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT id,path,sha256 FROM papers WHERE sha256 IS NOT NULL').fetchall()
            sqlite_ok = db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            foreign_keys_ok = not db.execute('PRAGMA foreign_key_check').fetchone()
            database_ok = sqlite_ok and foreign_keys_ok
            artifacts = bad_artifacts(db)
    directory = storage.pdf_directory(database)
    referenced = set()
    missing, changed = [], []
    for paper_id, path, expected in rows:
        path = Path(path).absolute()
        referenced.add(path)
        try:
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        except OSError:
            missing.append(paper_id)
            continue
        if actual != expected:
            changed.append(paper_id)
    orphans = sorted(str(p) for p in directory.glob('*/*') if p.is_file() and p.absolute() not in referenced)
    return {'database_ok': database_ok, 'missing': missing, 'changed': changed,
            'orphans': orphans, 'changed_artifacts': artifacts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', nargs='?', type=Path)
    args = parser.parse_args()
    try:
        result = check(storage.configuration(args.database))
    except storage.ERRORS + (OSError, ValueError) as error:
        parser.exit(1, f'Integrity check failed: {error}\n')
    print('Database:', 'OK' if result['database_ok'] else 'FAILED')
    problems = ('missing', 'changed', 'orphans', 'changed_artifacts')
    for label in problems:
        print(f'{label.title()}: {len(result[label])}')
        for item in result[label]:
            print(f'  {item}')
    if not result['database_ok'] or any(result[label] for label in problems):
        parser.exit(1)


if __name__ == '__main__':
    main()
