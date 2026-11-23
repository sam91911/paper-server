"""Database configuration and the PostgreSQL implementation of the SQL interface."""

import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


class PostgreSQLError(Exception):
    pass


class PostgreSQLIntegrityError(PostgreSQLError):
    pass


ERRORS = (sqlite3.Error, PostgreSQLError)
INTEGRITY_ERRORS = (sqlite3.IntegrityError, PostgreSQLIntegrityError)
WRITE_LOCK = 675158100967108815
UTC_TIMESTAMP = "(to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))"
SQL_TOKEN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|(?<!:):[a-zA-Z_]\w*|\?|\bCURRENT_TIMESTAMP\b")


@dataclass(frozen=True)
class PostgreSQL:
    url: str = field(repr=False)
    pdf_dir: Path


def configuration(sqlite_path=None):
    url = os.environ.get("PAPER_DATABASE_URL")
    if not url:
        return Path(sqlite_path or "papers.sqlite3").absolute()
    if sqlite_path is not None:
        raise ValueError("Choose --database or PAPER_DATABASE_URL.")
    directory = os.environ.get("PAPER_PDF_DIR")
    if not directory or not url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Set a PostgreSQL URI in PAPER_DATABASE_URL and a directory in PAPER_PDF_DIR.")
    return PostgreSQL(url, Path(directory).resolve())


def pdf_directory(target):
    if isinstance(target, PostgreSQL):
        return target.pdf_dir
    path = Path(target).absolute()
    return path.with_name(path.name + ".pdfs")


def begin(db, *, write=False):
    if isinstance(db, PostgreSQLConnection):
        db.execute("BEGIN" if write else "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if write:
            db.execute("SELECT pg_advisory_xact_lock(?)", (WRITE_LOCK,))
    else:
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")


def sql_for_postgres(sql, *, parameters):
    # Only translate placeholders and the app's UTC timestamp expression.
    # Quoted SQL literals and identifiers can contain placeholder characters.
    def translate(match):
        token = match[0]
        if token == "CURRENT_TIMESTAMP":
            return UTC_TIMESTAMP
        if parameters:
            if token == "?":
                return "%s"
            if token.startswith(":"):
                return "%(" + token[1:] + ")s"
        return token
    return SQL_TOKEN.sub(translate, sql.replace("%", "%%") if parameters else sql)


class Row(tuple):
    """Like sqlite3.Row, provide positional iteration and named access."""
    def __new__(cls, columns, values):
        row = super().__new__(cls, values)
        row.columns = columns
        return row

    def keys(self):
        return self.columns

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                key = self.columns.index(key)
            except ValueError as error:
                raise IndexError(key) from error
        return super().__getitem__(key)


def row_factory(cursor):
    columns = tuple(column.name for column in cursor.description or ())
    return lambda values: Row(columns, values)


def database_error(error, driver):
    # The driver detail can contain connection options or submitted data.
    kind = PostgreSQLIntegrityError if isinstance(error, driver.IntegrityError) else PostgreSQLError
    return kind("PostgreSQL operation failed (" + (error.sqlstate or type(error).__name__) + ").")


class PostgreSQLConnection:
    def __init__(self, connection, driver):
        self.connection = connection
        self.driver = driver

    def execute(self, sql, params=None):
        try:
            return self.connection.execute(sql_for_postgres(sql, parameters=params is not None), params)
        except self.driver.Error as error:
            raise database_error(error, self.driver) from None

    def executemany(self, sql, rows):
        try:
            with self.connection.cursor() as cursor:
                cursor.executemany(sql_for_postgres(sql, parameters=True), rows)
        except self.driver.Error as error:
            raise database_error(error, self.driver) from None


@contextmanager
def connect_postgres(target):
    try:
        import psycopg
    except ImportError:
        raise PostgreSQLError("Install the postgres extra to use PostgreSQL.") from None
    try:
        with psycopg.connect(target.url, cursor_factory=psycopg.ClientCursor, row_factory=row_factory) as connection:
            yield PostgreSQLConnection(connection, psycopg)
    except psycopg.Error as error:
        raise database_error(error, psycopg) from None


def initialize_postgres(db, *, require_empty=False):
    begin(db, write=True)
    if require_empty and db.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE' LIMIT 1"
    ).fetchone():
        raise ValueError("Migration requires an empty PostgreSQL database.")
    db.connection.execute("CREATE TABLE IF NOT EXISTS paper_schema_migrations (version INTEGER PRIMARY KEY)")
    applied = {version for (version,) in db.connection.execute("SELECT version FROM paper_schema_migrations")}
    migrations = sorted(Path(__file__).with_name("sql").glob("[0-9]*_*.sql"))
    versions = {int(path.name.split("_", 1)[0]) for path in migrations}
    if applied - versions:
        raise PostgreSQLError("The PostgreSQL schema is newer than this application.")
    for path in migrations:
        version = int(path.name.split("_", 1)[0])
        if version not in applied:
            db.connection.execute(path.read_text(encoding="utf-8"))
            db.execute("INSERT INTO paper_schema_migrations VALUES (?)", (version,))
    db.execute("INSERT INTO comment_id_sequence SELECT 1, COALESCE(MAX(id), 0) FROM comments ON CONFLICT DO NOTHING")
