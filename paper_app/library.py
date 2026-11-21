"""SQLite storage for papers, metrics, and library organization."""

import csv
import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import accounts, experiments, google_signin, sharing, tools_catalog

FIELDS = ("paper", "page", "metric", "value", "unit", "conditions", "evidence")
METADATA = ("doi", "title", "authors", "year", "venue", "publisher", "source")

COMMENT_COLUMNS = (
    "id", "paper_id", "body", "updated", "parent_id", "audience", "deleted",
    "doi_refs", "target_kind", "target_id", "target_position",
)
COMMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY,
    paper_id INTEGER REFERENCES papers(id),
    document_id INTEGER REFERENCES documents(id),
    body TEXT NOT NULL,
    updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    parent_id INTEGER REFERENCES comments(id) ON DELETE SET NULL,
    audience TEXT CHECK (audience IN ('owner','users','local','all','ai')),
    deleted INTEGER NOT NULL DEFAULT 0,
    doi_refs TEXT NOT NULL DEFAULT '[]',
    target_kind TEXT,
    target_id INTEGER,
    target_position INTEGER,
    CHECK ((paper_id IS NULL) != (document_id IS NULL))
);
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY, path TEXT NOT NULL, sha256 TEXT UNIQUE,
    doi TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
    authors TEXT NOT NULL DEFAULT '', year TEXT NOT NULL DEFAULT '',
    venue TEXT NOT NULL DEFAULT '', publisher TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS paper_metadata_checks (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id),
    allow_title INTEGER NOT NULL DEFAULT 0,
    next_check INTEGER NOT NULL DEFAULT 0,
    detected_doi TEXT
);
CREATE TABLE IF NOT EXISTS archived_papers (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id)
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
CREATE TABLE IF NOT EXISTS comment_id_sequence (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1), last_id INTEGER NOT NULL
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
        db.executescript(SCHEMA + COMMENT_SCHEMA.format(table="comments") + accounts.SCHEMA
                         + sharing.SCHEMA + google_signin.SCHEMA + experiments.SCHEMA + tools_catalog.SCHEMA)
        # Existing comments have a mandatory paper_id. Rebuild with the same IDs
        # so authors, grants, reply links, and anchors survive the migration.
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("BEGIN IMMEDIATE")
        accounts.initialize(db)
        sharing.initialize(db)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(comments)")}
        if "document_id" not in columns:
            db.execute(COMMENT_SCHEMA.format(table="comments_new"))
            existing = ", ".join(name for name in COMMENT_COLUMNS if name in columns)
            db.execute(f"INSERT INTO comments_new({existing}) SELECT {existing} FROM comments")
            db.execute("DROP TABLE comments")
            db.execute("ALTER TABLE comments_new RENAME TO comments")
        db.execute("CREATE INDEX IF NOT EXISTS comments_parent ON comments(parent_id)")
        db.execute("CREATE INDEX IF NOT EXISTS comments_paper_root ON comments(paper_id, parent_id)")
        db.execute("CREATE INDEX IF NOT EXISTS comments_document_root ON comments(document_id, parent_id)")
        db.execute("CREATE INDEX IF NOT EXISTS documents_updated ON documents(updated DESC, id DESC)")
        db.execute("INSERT OR IGNORE INTO comment_id_sequence SELECT 1, COALESCE(MAX(id), 0) FROM comments")
        for table in ("comments", "comment_authors"):
            if db.execute(f"PRAGMA foreign_key_check({table})").fetchone():
                raise sqlite3.IntegrityError("Invalid comment references during migration")


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


def metric_rows(db, account=None):
    rows = db.execute(
        sharing.PAPER_SCOPE +
        "SELECT m.*, p.path AS paper FROM metrics m JOIN visible_papers p ON p.id=m.paper_id "
        "WHERE p.id NOT IN (SELECT paper_id FROM archived_papers) "
        "ORDER BY m.paper_id, m.page, m.metric, m.value, m.unit, m.conditions, m.evidence",
        sharing.viewer_params(account),
    )
    for row in rows:
        if account and account["role"] != "user":
            yield dict(row, paper=Path(row["paper"]).name)
        else:
            yield row


def metric_page(db, account=None, *, after=0, limit=500):
    """Return a bounded, access-filtered page using SQLite's metric rowid."""
    rows = db.execute(
        sharing.PAPER_SCOPE +
        "SELECT m.rowid AS cursor, m.*, p.path AS paper FROM metrics m "
        "JOIN visible_papers p ON p.id=m.paper_id "
        "WHERE m.rowid>:after AND p.id NOT IN (SELECT paper_id FROM archived_papers) "
        "ORDER BY m.rowid LIMIT :limit",
        sharing.viewer_params(account, after=after, limit=limit + 1),
    ).fetchall()
    more = len(rows) > limit
    page = [dict(row) for row in rows[:limit]]
    next_cursor = page[-1]["cursor"] if more else None
    for row in page:
        row.pop("cursor")
        if account and account["role"] != "user":
            row["paper"] = Path(row["paper"]).name
    return {"metrics": page, "next_after": next_cursor}


def paper_page(db, account=None, *, after=0, limit=100):
    rows = db.execute(
        sharing.PAPER_SCOPE +
        "SELECT id,path,doi,title,authors,year,venue,publisher,source,owner_id,audience, "
        "sha256 IS NOT NULL AS has_pdf FROM visible_papers "
        "WHERE id>:after AND id NOT IN (SELECT paper_id FROM archived_papers) "
        "ORDER BY id LIMIT :limit",
        sharing.viewer_params(account, after=after, limit=limit + 1),
    ).fetchall()
    more = len(rows) > limit
    page = [dict(row) for row in rows[:limit]]
    if not account or account["role"] != "user":
        for row in page:
            row["path"] = Path(row["path"]).name
    return {"papers": page, "next_after": page[-1]["id"] if more else None}


def snapshot(db, view="library", account=None, *, include_comments=True, document_summaries=False):
    def rows(query):
        return [dict(row) for row in db.execute(sharing.PAPER_SCOPE + query, sharing.viewer_params(account))]

    is_human = account is not None and account["role"] == "user"
    paper_columns = "id, path, title" if view == "compare" else (
        "id, path, doi, title, authors, year, venue, publisher, source, owner_id, audience"
    )
    if view == "library":
        paper_columns = "*"
    else:
        paper_columns += ", sha256 IS NOT NULL AS has_pdf"
    if view == "paper-details":
        paper_columns += ", COALESCE((SELECT allow_title FROM paper_metadata_checks WHERE paper_id=id),0) AS allow_title"
    data = {
        "papers": rows(f"SELECT {paper_columns} FROM visible_papers "
                       "WHERE id NOT IN (SELECT paper_id FROM archived_papers) ORDER BY path"),
        "groups": [dict(row) for row in db.execute("SELECT * FROM groups ORDER BY name")] if is_human else [],
        "memberships": rows(
            "SELECT * FROM memberships WHERE paper_id IN (SELECT id FROM visible_papers) "
            "AND paper_id NOT IN (SELECT paper_id FROM archived_papers)"
        ) if is_human else [],
    }
    if not is_human:
        for paper in data["papers"]:
            paper["path"] = Path(paper["path"]).name
    if view == "documents":
        return {"account": account, "documents": sharing.documents_for(db, account, summaries=document_summaries), "papers": data["papers"],
                "comments": comment_snapshot(db, account, documents=True) if include_comments else []}
    if view in ("paper-details", "compare"):
        data["account"] = account
    if view == "paper-details":
        sharing.attach_recipients(db, "paper", data["papers"], account)
        data["document_targets"] = sharing.documents_for(db, account, targets_only=True)
        data["archived_papers"] = rows(
            "SELECT id, path, title, owner_id FROM visible_papers JOIN archived_papers ON id=paper_id "
            "WHERE owner_id IS NULL OR owner_id=:viewer ORDER BY path"
        )
        if not is_human:
            for paper in data["archived_papers"]:
                paper["path"] = Path(paper["path"]).name
    else:
        data["metrics"] = [dict(row) for row in metric_rows(db, account)]
    if view != "compare":
        data["comments"] = comment_snapshot(db, account) if include_comments else []
    return data


def comment_snapshot(db, account, *, documents=False, paper_id=None, document_id=None, before=None, root_limit=None):
    root_scope = (
        "c.document_id IN (SELECT id FROM visible_documents)" if documents else
        "c.paper_id IN (SELECT id FROM visible_papers) "
        "AND c.paper_id NOT IN (SELECT paper_id FROM archived_papers)"
    )
    if paper_id is not None:
        root_scope += " AND c.paper_id=:paper_filter"
    if document_id is not None:
        root_scope += " AND c.document_id=:document_filter"
    if before is not None:
        root_scope += " AND c.id<:before"
    root_order = " ORDER BY c.id DESC LIMIT :root_limit" if root_limit is not None else ""
    items = [dict(row) for row in db.execute(
        sharing.PAPER_SCOPE + f""", root_comments AS (
            SELECT c.* FROM comments c WHERE {root_scope}
            AND c.parent_id IS NULL AND {comment_access_sql()}{root_order}
        ), visible_comments AS (
            SELECT * FROM root_comments
            UNION ALL
            SELECT c.* FROM comments c JOIN visible_comments parent ON c.parent_id=parent.id
            WHERE {comment_access_sql()}
        )
        SELECT c.*, a.account_id AS author_id, a.kind AS author_kind,
               COALESCE(NULLIF(u.display_name,''),u.username) AS author_name,
               {accounts.ROLE_SQL.format(alias="u")} AS author_role
        FROM visible_comments c LEFT JOIN comment_authors a ON a.comment_id=c.id
        LEFT JOIN accounts u ON a.account_id=u.id ORDER BY c.id
        """,
        sharing.viewer_params(account, paper_filter=paper_id, document_filter=document_id, before=before, root_limit=root_limit),
    )]
    sharing.attach_recipients(db, "comment", items, account, "author_id")
    for comment in items:
        comment["doi_refs"] = json.loads(comment["doi_refs"])
        if comment["deleted"]:
            comment.pop("recipients", None)
            comment.update(author_id=None, author_kind=None, author_name=None, author_role=None,
                           target_kind=None, target_id=None, target_position=None)
    return items


def save_metadata(db, paper_id, data):
    values = [data.get(field, "") for field in METADATA]
    if any(not isinstance(value, str) or len(value) > 4000 for value in values):
        raise ValueError("Invalid metadata fields")
    if db.execute(
        "UPDATE papers SET doi=?,title=?,authors=?,year=?,venue=?,publisher=?,source=? WHERE id=?",
        (*values, paper_id),
    ).rowcount == 0:
        raise ValueError("Paper not found")


def encode_doi_refs(values):
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError("Use up to 20 DOI references.")
    dois = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Enter a DOI or doi.org link.")
        doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I)
        if not re.fullmatch(r"10\.\d{4,9}/[^\s<>\x00-\x1f\x7f]{1,400}", doi, re.ASCII):
            raise ValueError("Enter a DOI or doi.org link.")
        dois.append(doi)
    return json.dumps(list(dict.fromkeys(dois)))


def comment_access_sql():
    owner = "(SELECT account_id FROM comment_authors WHERE comment_id=c.id)"
    audience = sharing.access_sql(owner, "c.audience", "comment", "c.id")
    document_audience = sharing.access_sql("d.owner_id", "d.audience", "document", "d.id")
    return f"""(c.audience IS NULL OR {audience}) AND
        (c.target_kind IS NULL
         OR (c.target_kind='pdf' AND c.target_id IN (SELECT id FROM visible_papers WHERE sha256 IS NOT NULL))
         OR (c.target_kind='document' AND EXISTS (
             SELECT 1 FROM documents d WHERE d.id=c.target_id AND {document_audience})))"""


def comment_target(db, account, location):
    if location is None:
        return None, None, None
    if not isinstance(location, dict):
        raise ValueError("Choose a PDF page or document line.")
    kind, target_id, position = (location.get(field) for field in ("kind", "id", "position"))
    if (kind not in ("pdf", "document") or type(target_id) is not int or not 0 < target_id < 2**63
        or type(position) is not int or not 0 < position <= 1_000_000):
        raise ValueError("Choose a target and a positive page or line number.")
    if kind == "pdf":
        if not sharing.paper_for(db, target_id, account)["sha256"]:
            raise sharing.AccessDenied
    else:
        doc = sharing.document_for(db, account, target_id)
        if doc is None:
            raise sharing.AccessDenied
        if position > doc["markdown"].count("\n") + 1:
            raise ValueError("This document has no such line.")
    return kind, target_id, position


def can_reply(db, paper_id, parent_id, account, document_id=None):
    return db.execute(
        sharing.PAPER_SCOPE + """, ancestors AS (
            SELECT * FROM comments WHERE id=:parent AND paper_id IS :paper AND document_id IS :document AND deleted=0
            UNION ALL SELECT c.* FROM comments c JOIN ancestors a ON c.id=a.parent_id
        )
        SELECT COUNT(*) > 0 AND COUNT(*) = SUM(CASE WHEN """ + comment_access_sql() + """ THEN 1 ELSE 0 END)
        FROM ancestors c""",
        sharing.viewer_params(account, paper=paper_id, document=document_id, parent=parent_id),
    ).fetchone()[0]


def save_comment(db, paper_id, body, account, comment_id=None, kind="user",
                 parent_id=None, doi_refs=None, audience=None, location=None, recipients=None, document_id=None):
    account_id = account["id"]
    if account["role"] in ("local", "cloud"):
        kind = "ai"
    if audience is not None:
        sharing.validate_audience(audience)
    references = encode_doi_refs(doi_refs) if doi_refs is not None else None
    if not isinstance(body, str) or not body.strip() or len(body) > 20000:
        raise ValueError("Enter a comment of up to 20,000 characters")
    if comment_id is not None and location is not None:
        raise ValueError("The location of a posted comment is fixed.")
    if comment_id is None:
        target = comment_target(db, account, location)
        if kind not in ("user", "ai"):
            raise ValueError("Choose a comment author.")
        if parent_id is not None and (type(parent_id) is not int or not can_reply(db, paper_id, parent_id, account, document_id)):
            raise ValueError("Select an accessible comment on this item to reply to.")
        db.execute("UPDATE comment_id_sequence SET last_id=last_id+1 WHERE singleton=1")
        cursor = db.execute(
            "INSERT INTO comments(id,paper_id,document_id,body,parent_id,doi_refs,audience,"
            "target_kind,target_id,target_position) "
            "SELECT last_id,?,?,?,?,?,?,?,?,? FROM comment_id_sequence WHERE singleton=1",
            (paper_id, document_id, body.strip(), parent_id, references or "[]", audience or "owner", *target),
        )
        comment_id = cursor.lastrowid
        db.execute("INSERT INTO comment_authors VALUES (?,?,?)", (comment_id, account_id, kind))
    elif not can_reply(db, paper_id, comment_id, account, document_id) or db.execute(
        "UPDATE comments SET body=?,doi_refs=COALESCE(?,doi_refs),audience=COALESCE(?,audience), "
        "updated=CURRENT_TIMESTAMP WHERE paper_id IS ? AND document_id IS ? AND id=? AND deleted=0 "
        "AND id IN (SELECT comment_id FROM comment_authors WHERE account_id=?)",
        (body.strip(), references, audience, paper_id, document_id, comment_id, account_id),
    ).rowcount == 0:
        raise accounts.CommentAccessDenied
    sharing.set_recipients(db, "comment", comment_id, recipients)
    return comment_id


def delete_comment(db, paper_id, comment_id, account_id, document_id=None):
    if db.execute(
        "UPDATE comments SET deleted=1,body='',doi_refs='[]',updated=CURRENT_TIMESTAMP "
        "WHERE paper_id IS ? AND document_id IS ? AND id=? AND deleted=0 "
        "AND id IN (SELECT comment_id FROM comment_authors WHERE account_id=?)",
        (paper_id, document_id, comment_id, account_id),
    ).rowcount == 0:
        raise accounts.CommentAccessDenied


def set_archived(db, paper_id, archived):
    if not db.execute("SELECT id FROM papers WHERE id=?", (paper_id,)).fetchone():
        raise ValueError("Paper not found")
    if archived:
        db.execute("INSERT OR IGNORE INTO archived_papers VALUES (?)", (paper_id,))
    else:
        db.execute("DELETE FROM archived_papers WHERE paper_id=?", (paper_id,))


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
