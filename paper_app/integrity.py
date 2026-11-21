"""Read-only checks for missing, altered, and unreferenced stored PDFs."""
import argparse
import hashlib
import sqlite3
from pathlib import Path


def check(database):
    database = database.resolve(strict=True)
    directory = database.with_name(database.name + '.pdfs')
    with sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id,path,sha256 FROM papers WHERE sha256 IS NOT NULL').fetchall()
        sqlite_ok = db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        foreign_keys_ok = not db.execute('PRAGMA foreign_key_check').fetchone()
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
    return {'database_ok': sqlite_ok and foreign_keys_ok, 'missing': missing, 'changed': changed, 'orphans': orphans}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    try:
        result = check(args.database)
    except (OSError, sqlite3.Error) as error:
        parser.exit(1, f'Integrity check failed: {error}\n')
    print('Database:', 'OK' if result['database_ok'] else 'FAILED')
    for label in ('missing', 'changed', 'orphans'):
        print(f'{label.title()}: {len(result[label])}')
        for item in result[label]:
            print(f'  {item}')
    if not result['database_ok'] or result['missing'] or result['changed'] or result['orphans']:
        parser.exit(1)


if __name__ == '__main__':
    main()
