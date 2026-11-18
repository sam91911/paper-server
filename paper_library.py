"""SQLite storage shared by the metrics extractor and local paper server."""

import csv
import math
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

FIELDS = ("paper", "page", "metric", "value", "unit", "conditions", "evidence")
METADATA = ("doi", "title", "authors", "year", "venue", "publisher", "source")

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY, path TEXT NOT NULL, sha256 TEXT UNIQUE,
    doi TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
    authors TEXT NOT NULL DEFAULT '', year TEXT NOT NULL DEFAULT '',
    venue TEXT NOT NULL DEFAULT '', publisher TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS paper_paths (
    path TEXT PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id)
);
CREATE TABLE IF NOT EXISTS metrics (
    paper_id INTEGER NOT NULL REFERENCES papers(id), page INTEGER NOT NULL,
    metric TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL,
    conditions TEXT NOT NULL, evidence TEXT NOT NULL,
    PRIMARY KEY (paper_id, page, metric, value, unit, conditions, evidence)
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id),
    body TEXT NOT NULL, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE
);
CREATE TABLE IF NOT EXISTS memberships (
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    group_id INTEGER NOT NULL REFERENCES groups(id),
    PRIMARY KEY (paper_id, group_id)
);
"""


@contextmanager
def connect(path):
    if not Path(path).exists():
        descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys = ON")
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.executescript(SCHEMA)


def store(db, path, rows, digest=None, base=None):
    path = Path(path)
    if base is not None and not path.is_absolute():
        path = base / path
    key = os.path.abspath(path)
    alias = db.execute(
        "SELECT p.id, p.sha256 FROM paper_paths a JOIN papers p ON p.id=a.paper_id WHERE a.path=?",
        (key,),
    ).fetchone()
    match = db.execute("SELECT id FROM papers WHERE sha256=?", (digest,)).fetchone() if digest else None
    if alias and digest and alias["sha256"] not in (None, digest):
        raise ValueError(f"PDF contents changed at {key}; import under a new path")
    if alias and match and alias["id"] != match["id"]:
        raise ValueError(f"Path and PDF hash refer to different library records: {key}")
    if alias or match:
        paper_id = (alias or match)["id"]
        if digest and not match:
            db.execute("UPDATE papers SET sha256=? WHERE id=?", (digest, paper_id))
    else:
        paper_id = db.execute("INSERT INTO papers(path,sha256) VALUES (?,?)", (key, digest)).lastrowid
    db.execute("INSERT OR IGNORE INTO paper_paths VALUES (?,?)", (key, paper_id))
    db.executemany("INSERT OR IGNORE INTO metrics VALUES (?,?,?,?,?,?,?)",
                   ((paper_id, *row) for row in rows))
    return paper_id


def import_csv(db, stream, base):
    reader = csv.DictReader(stream, strict=True)
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise ValueError("Expected the extractor's seven CSV columns")
    papers = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Wrong number of fields on CSV line {reader.line_num}")
        try:
            page = int(row["page"])
            value = float(row["value"])
        except ValueError as error:
            raise ValueError(f"Invalid page or value on CSV line {reader.line_num}") from error
        if page < 1 or not math.isfinite(value) or not row["paper"].strip() or not row["metric"].strip():
            raise ValueError(f"Invalid metric on CSV line {reader.line_num}")
        papers.setdefault(row["paper"], []).append((page, *(row[key] for key in FIELDS[2:])))
    for paper, rows in papers.items():
        store(db, paper, rows, base=base)
    return len(papers)


def snapshot(db, view="library"):
    paper_columns = "id, path, title" if view == "compare" else "id, path, doi, title, authors, year, venue, publisher, source"
    if view == "library":
        paper_columns = "*"
    data = {
        "papers": [dict(row) for row in db.execute(f"SELECT {paper_columns} FROM papers ORDER BY path")],
        "groups": [dict(row) for row in db.execute("SELECT * FROM groups ORDER BY name")],
        "memberships": [dict(row) for row in db.execute("SELECT * FROM memberships")],
    }
    if view != "paper-details":
        data["metrics"] = [dict(row) for row in db.execute(
            "SELECT m.*, p.path AS paper FROM metrics m JOIN papers p ON p.id=m.paper_id ORDER BY m.paper_id,m.page"
        )]
    if view != "compare":
        data["comments"] = [dict(row) for row in db.execute("SELECT * FROM comments ORDER BY id")]
    return data


def save_metadata(db, paper_id, data):
    values = [data.get(field, "") for field in METADATA]
    if any(not isinstance(value, str) or len(value) > 4000 for value in values):
        raise ValueError("Invalid metadata fields")
    if db.execute(
        "UPDATE papers SET doi=?,title=?,authors=?,year=?,venue=?,publisher=?,source=? WHERE id=?",
        (*values, paper_id),
    ).rowcount == 0:
        raise ValueError("Paper not found")


def save_comment(db, paper_id, body, comment_id=None):
    if not isinstance(body, str) or not body.strip() or len(body) > 20000:
        raise ValueError("Enter a comment of up to 20,000 characters")
    if comment_id is None:
        db.execute("INSERT INTO comments(paper_id,body) VALUES (?,?)", (paper_id, body.strip()))
    elif db.execute(
        "UPDATE comments SET body=?,updated=CURRENT_TIMESTAMP WHERE paper_id=? AND id=?",
        (body.strip(), paper_id, comment_id),
    ).rowcount == 0:
        raise ValueError("Comment not found")


def create_group(db, name):
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("Enter a group name of up to 120 characters")
    db.execute("INSERT INTO groups(name) VALUES (?)", (name.strip(),))


def set_memberships(db, paper_id, groups):
    if not isinstance(groups, list) or any(type(group) is not int for group in groups):
        raise ValueError("Invalid groups")
    if not db.execute("SELECT id FROM papers WHERE id=?", (paper_id,)).fetchone():
        raise ValueError("Paper not found")
    db.execute("DELETE FROM memberships WHERE paper_id=?", (paper_id,))
    db.executemany("INSERT INTO memberships VALUES (?,?)",
                   ((paper_id, group) for group in set(groups)))
