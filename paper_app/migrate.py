"""Copy an offline SQLite library and its PDFs into a new PostgreSQL database."""

import argparse
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from . import database, integrity, library


def stage_source(source, snapshot):
    snapshot.touch(mode=0o600)
    with database.read_sqlite(source) as original, closing(sqlite3.connect(snapshot)) as copy:
        original.backup(copy)
    library.initialize(snapshot)


def stage_pdfs(db, staged, destination):
    for paper_id, path, expected in db.execute("SELECT id,path,sha256 FROM papers WHERE sha256 IS NOT NULL"):
        original = Path(path)
        if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected) or not original.name:
            raise ValueError(f"Invalid stored PDF metadata for paper {paper_id}.")
        relative = Path(expected) / original.name
        copy = staged / relative
        copy.parent.mkdir(mode=0o700, exist_ok=True)
        try:
            shutil.copyfile(original, copy)
        except OSError as error:
            raise ValueError(f"Could not copy the PDF for paper {paper_id}.") from error
        copy.chmod(0o600)
        if integrity.file_sha256(copy) != expected:
            raise ValueError(f"PDF integrity check failed for paper {paper_id}.")
        final = str(destination / relative)
        db.execute("UPDATE papers SET path=? WHERE id=?", (final, paper_id))
        db.execute("UPDATE paper_paths SET path=? WHERE paper_id=? AND path=?", (final, paper_id, path))


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def copy_tables(source, db):
    db.execute("SET CONSTRAINTS ALL DEFERRED")
    tables = db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() "
        "AND table_type='BASE TABLE' AND table_name <> 'paper_schema_migrations' ORDER BY table_name"
    )
    source_tables = {name for (name,) in source.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )}
    for (name,) in tables:
        if name not in source_tables:
            raise ValueError(f"Source is missing table {name}.")
        source_tables.remove(name)
        table = quote(name)
        target_columns = db.execute(
            "SELECT column_name,data_type,is_identity FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=?", (name,),
        ).fetchall()
        identity = next((column for column, _, flag in target_columns if flag == "YES"), None)
        booleans = {column for column, data_type, _ in target_columns if data_type == "boolean"}
        rows = source.execute(f"SELECT * FROM {table}")
        columns = [column[0] for column in rows.description]
        field_names = ", ".join(map(quote, columns))
        markers = ", ".join("?" for _ in columns)
        # Initialization seeds the comment sequence; the copy supplies its value.
        if name == "comment_id_sequence":
            db.execute("DELETE FROM comment_id_sequence")
        values = (tuple(bool(value) if column in booleans and value is not None else value
                        for column, value in zip(columns, row)) for row in rows) if booleans else rows
        db.executemany(f"INSERT INTO {table} ({field_names}) VALUES ({markers})", values)
        expected = source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] != expected:
            raise ValueError(f"Row count verification failed for {name}.")
        if identity:
            column = identity
            latest = db.execute(f"SELECT MAX({quote(column)}) FROM {table}").fetchone()[0]
            if name == "application_keys":
                high_water = source.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (name,)).fetchone()
                if high_water:
                    latest = max(latest or 0, high_water[0])
            db.execute("SELECT setval(pg_get_serial_sequence(?, ?), ?, ?)",
                       (table, column, max(latest or 1, 1), bool(latest and latest > 0)))
    if source_tables:
        raise ValueError(f"Source has unmapped tables: {', '.join(sorted(source_tables))}.")
    db.execute("SET CONSTRAINTS ALL IMMEDIATE")


def migrate(source, target):
    destination = target.pdf_dir
    if destination.exists():
        raise ValueError("Migration requires a new PAPER_PDF_DIR.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    published = False
    with tempfile.TemporaryDirectory(prefix=".paper-migration-", dir=destination.parent) as directory:
        root = Path(directory)
        snapshot = root / "source.sqlite3"
        stage_source(source, snapshot)
        files = root / "pdfs"
        files.mkdir(mode=0o700)
        try:
            with closing(sqlite3.connect(snapshot)) as original, library.connect(target) as db:
                if (original.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or original.execute("PRAGMA foreign_key_check").fetchone()
                    or integrity.bad_artifacts(original)):
                    raise ValueError("SQLite source failed integrity checks.")
                stage_pdfs(original, files, destination)
                database.initialize_postgres(db, require_empty=True)
                copy_tables(original, db)
                files.rename(destination)
                published = True
        except database.PostgreSQLError as error:
            if published:
                # The server may have committed before the connection failed.
                raise ValueError("Database completion is uncertain. The published PDFs are available for verification.") from error
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-sqlite", required=True, type=Path)
    args = parser.parse_args()
    try:
        target = database.configuration()
        if not isinstance(target, database.PostgreSQL):
            raise ValueError("Set PAPER_DATABASE_URL and PAPER_PDF_DIR for the migration target.")
        migrate(args.from_sqlite, target)
    except database.ERRORS + (OSError, ValueError) as error:
        parser.exit(1, f"Migration failed: {error}\n")
    print("SQLite library migrated to PostgreSQL.")


if __name__ == "__main__":
    main()
