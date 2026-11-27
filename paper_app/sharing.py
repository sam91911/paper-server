"""Account-based access to PDFs and Markdown documents."""

from urllib.parse import urlsplit

from . import accounts

AUDIENCES = ("owner", "users", "local", "all", "ai")
UNSET = object()
HISTORY_SCHEMA = ("""
CREATE TABLE IF NOT EXISTS document_versions (
    document_id INTEGER NOT NULL REFERENCES documents(id), revision INTEGER NOT NULL,
    title TEXT NOT NULL, markdown TEXT NOT NULL, source_url TEXT NOT NULL,
    author TEXT NOT NULL, saved TEXT NOT NULL, PRIMARY KEY (document_id,revision)
)
""", """
CREATE TABLE IF NOT EXISTS thread_votes (
    kind TEXT NOT NULL CHECK(kind IN ('discussion','comment')), target_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id), value INTEGER NOT NULL CHECK(value IN (-1,1)),
    PRIMARY KEY(kind,target_id,account_id)
)
""")
GRANTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS item_grants (
    kind TEXT NOT NULL CHECK (kind IN ('paper','document','comment','skill','research_goal')),
    item_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    PRIMARY KEY (kind,item_id,account_id)
);
"""
SCHEMA = GRANTS_SCHEMA + """
CREATE TABLE IF NOT EXISTS paper_access (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id),
    owner_id INTEGER NOT NULL REFERENCES accounts(id),
    audience TEXT NOT NULL CHECK (audience IN ('owner', 'users', 'local', 'all', 'ai'))
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES accounts(id),
    audience TEXT NOT NULL CHECK (audience IN ('owner', 'users', 'local', 'all', 'ai')),
    title TEXT NOT NULL,
    markdown TEXT NOT NULL,
    updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


MANAGED_AGENTS_SQL = """SELECT o.agent_id FROM ai_operators o JOIN accounts agent ON agent.id=o.agent_id
                        WHERE o.operator_id=:viewer AND :role='user' AND agent.role='ai'"""


def owner_sql(owner):
    return f"({owner}=:viewer OR {owner} IN ({MANAGED_AGENTS_SQL}))"


def owner_ids(db, account):
    if not account:
        return set()
    owned = {account["id"]}
    if account["role"] == "user":
        owned.update(row[0] for row in db.execute(MANAGED_AGENTS_SQL, viewer_params(account)))
    return owned


def is_owner(db, account, owner_id):
    if not account or owner_id is None:
        return False
    if owner_id == account["id"]:
        return True
    return account["role"] == "user" and db.execute(
        f"SELECT 1 WHERE :owner IN ({MANAGED_AGENTS_SQL})", viewer_params(account, owner=owner_id),
    ).fetchone() is not None


def access_sql(owner, audience, kind, item_id):
    return f"""({owner_sql(owner)} OR (:viewer IS NOT NULL AND (
       ({audience} = 'all' AND :role IN ('user', 'local', 'cloud'))
       OR ({audience} = 'users' AND :role = 'user')
       OR ({audience} = 'local' AND :role IN ('user', 'local'))
       OR ({audience} = 'ai' AND :role = 'local')
       OR EXISTS (SELECT 1 FROM item_grants grant_entry WHERE grant_entry.kind='{kind}'
                  AND grant_entry.item_id={item_id} AND grant_entry.account_id=:viewer))))"""


PAPER_SCOPE = f"""
    WITH RECURSIVE paper_permissions AS (
        SELECT p.*, access.owner_id, access.audience, metadata.audience AS metadata_audience,
            CASE WHEN (access.owner_id IS NULL AND :role = 'user')
                OR {access_sql('access.owner_id', 'access.audience', 'paper', 'p.id')}
                THEN 1 ELSE 0 END AS can_read_file
        FROM papers p LEFT JOIN paper_access access ON access.paper_id=p.id
        LEFT JOIN paper_metadata_access metadata ON metadata.paper_id=p.id
    ), visible_papers AS (
        SELECT p.* FROM paper_permissions p WHERE p.can_read_file=1
            OR (p.metadata_audience='all' AND :role='member')
            OR (p.metadata_audience IS NOT NULL
                AND {access_sql('p.owner_id', 'p.metadata_audience', 'paper', 'p.id')})
    ), visible_documents AS (
        SELECT d.* FROM documents d WHERE {access_sql("d.owner_id", "d.audience", "document", "d.id")}
    )
"""


def initialize(db):
    grants_sql, = db.execute("SELECT sql FROM sqlite_schema WHERE name='item_grants'").fetchone()
    if "'research_goal'" not in grants_sql:
        db.execute("ALTER TABLE item_grants RENAME TO old_item_grants")
        db.execute(GRANTS_SCHEMA)
        db.execute("INSERT INTO item_grants SELECT * FROM old_item_grants")
        db.execute("DROP TABLE old_item_grants")
    for table in ("paper_access", "documents"):
        sql, = db.execute("SELECT sql FROM sqlite_schema WHERE name=?", (table,)).fetchone()
        if "'local'" in sql:
            continue
        db.execute(f"ALTER TABLE {table} RENAME TO old_{table}")
        db.execute(sql.replace("'users', 'ai', 'all'", "'users', 'local', 'all', 'ai'"))
        db.execute(f"INSERT INTO {table} SELECT * FROM old_{table}")
        db.execute(f"UPDATE {table} SET audience='local' WHERE audience='all'")
        db.execute(f"DROP TABLE old_{table}")
    db.execute("""
        CREATE TABLE IF NOT EXISTS paper_metadata_access (
            paper_id INTEGER PRIMARY KEY REFERENCES paper_access(paper_id),
            audience TEXT NOT NULL CHECK (audience IN ('owner', 'users', 'local', 'all', 'ai'))
        )
    """)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(documents)")}
    if "revision" not in columns:
        db.execute("ALTER TABLE documents ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
    if "source_url" not in columns:
        db.execute("ALTER TABLE documents ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
    if "kind" not in columns:
        db.execute("ALTER TABLE documents ADD COLUMN kind TEXT NOT NULL DEFAULT 'document' CHECK(kind IN ('document','discussion'))")
    if "scheduled_at" not in columns:
        db.execute("ALTER TABLE documents ADD COLUMN scheduled_at INTEGER")
    for statement in HISTORY_SCHEMA:
        db.execute(statement)
    db.execute("""
        INSERT INTO document_versions(document_id,revision,title,markdown,source_url,author,saved)
        SELECT d.id,d.revision,d.title,d.markdown,d.source_url,a.username,d.updated
        FROM documents d JOIN accounts a ON a.id=d.owner_id WHERE d.kind='document'
        ON CONFLICT(document_id,revision) DO NOTHING
    """)


class AccessDenied(Exception):
    pass


class EditConflict(Exception):
    pass


def viewer_params(account, **extra):
    return {"viewer": account["id"] if account else None,
            "role": account["role"] if account else None, **extra}


def validate_audience(audience):
    if audience not in AUDIENCES:
        raise ValueError("Choose who can access this item.")
    return audience


def paper_for(db, paper_id, account, *, owner_only=False, file_access=False):
    row = db.execute(
        PAPER_SCOPE + "SELECT * FROM visible_papers WHERE id=:paper",
        viewer_params(account, paper=paper_id),
    ).fetchone()
    if (row is None or (file_access and not row["can_read_file"])
            or (owner_only and row["owner_id"] is not None and not is_owner(db, account, row["owner_id"]))):
        raise AccessDenied
    return row


def recipient_ids(db, recipients):
    if recipients is None:
        return
    if not isinstance(recipients, list) or len(recipients) > 50:
        raise ValueError("Share with up to 50 usernames.")
    names = {accounts.identity(name).lower() for name in recipients}
    ids = []
    for name in sorted(names):
        row = db.execute("SELECT id FROM accounts WHERE username=?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"No account with username {name}.")
        ids.append(row["id"])
    return ids


def set_recipients(db, kind, item_id, recipients):
    ids = recipient_ids(db, recipients)
    if ids is None:
        return
    db.execute("DELETE FROM item_grants WHERE kind=? AND item_id=?", (kind, item_id))
    db.executemany("INSERT INTO item_grants VALUES (?,?,?)",
                   ((kind, item_id, account_id) for account_id in ids))


def attach_recipients(db, kind, items, account, owner_field="owner_id"):
    if not account:
        return items
    owners = owner_ids(db, account)
    owned = {item["id"]: item for item in items if item.get(owner_field) in owners}
    for item in owned.values():
        item["can_manage"] = True
        item["recipients"] = []
    # Restrict the query to owned items in bounded batches; this avoids one
    # SQL query per item without exposing grants on other people's items.
    ids = list(owned)
    for start in range(0, len(ids), 500):
        batch = ids[start:start + 500]
        placeholders = ','.join('?' for _ in batch)
        for row in db.execute(
            "SELECT g.item_id,a.username FROM item_grants g JOIN accounts a ON a.id=g.account_id "
            f"WHERE g.kind=? AND g.item_id IN ({placeholders}) ORDER BY a.username",
            (kind, *batch),
        ):
            owned[row["item_id"]]["recipients"].append(row["username"])
    return items


def set_paper_audience(db, paper_id, account, audience, recipients=None):
    audience = validate_audience(audience)
    if db.execute(
        f"UPDATE paper_access SET audience=:audience WHERE paper_id=:paper AND {owner_sql('owner_id')}",
        viewer_params(account, audience=audience, paper=paper_id),
    ).rowcount == 0:
        raise AccessDenied
    set_recipients(db, "paper", paper_id, recipients)


def set_paper_metadata_audience(db, paper_id, audience):
    if audience is None:
        db.execute("DELETE FROM paper_metadata_access WHERE paper_id=?", (paper_id,))
        return
    db.execute(
        "INSERT INTO paper_metadata_access(paper_id,audience) VALUES (?,?) "
        "ON CONFLICT(paper_id) DO UPDATE SET audience=excluded.audience",
        (paper_id, validate_audience(audience)),
    )


def document_for(db, account, document_id):
    return db.execute(
        "SELECT * FROM documents d WHERE id=:document AND " + access_sql("d.owner_id", "d.audience", "document", "d.id"),
        viewer_params(account, document=document_id),
    ).fetchone()


def documents_for(db, account, *, targets_only=False, summaries=False, news_only=False, discussion_only=False):
    from . import document_context

    if targets_only:
        return [dict(row) for row in db.execute(
            "SELECT id,title FROM documents d WHERE " + access_sql("d.owner_id", "d.audience", "document", "d.id")
            + " AND d.kind='document' ORDER BY title",
            viewer_params(account),
        )]
    columns = "d.id,d.owner_id,d.audience,d.title,d.updated,d.revision,d.source_url,d.kind,d.scheduled_at" if summaries else "d.*"
    columns += "," + document_context.COLUMNS
    scope = " AND d.source_url<>''" if news_only else ""
    scope += " AND d.kind=:document_kind"
    if discussion_only:
        columns += "," + vote_columns("discussion", "d.id")
    items = [dict(row) for row in db.execute(
        f"SELECT {columns}, a.username AS owner_name, {accounts.ROLE_SQL.format(alias='a')} AS owner_role "
        f"FROM documents d JOIN accounts a ON a.id=d.owner_id{document_context.JOIN} WHERE "
        + access_sql("d.owner_id", "d.audience", "document", "d.id") + scope + " ORDER BY d.updated DESC, d.id DESC",
        viewer_params(account, document_kind="discussion" if discussion_only else "document"),
    )]
    return document_context.redact(db, account, attach_recipients(db, "document", items, account))


def validate_news_source(value):
    message = "Enter an HTTPS news source URL without credentials."
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(char.isspace() or ord(char) < 32 or char in "\\" for char in value)):
        raise ValueError(message)
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username is not None or url.port == 0:
            raise ValueError(message)
    except ValueError:
        raise ValueError(message) from None
    return value


def schedule_value(value):
    if value is not None and (type(value) is not int or not 0 <= value <= 253402300799):
        raise ValueError("Choose a scheduled time or clear it.")
    return value


def vote_columns(kind, row_id):
    votes = f"FROM thread_votes v WHERE v.kind='{kind}' AND v.target_id={row_id}"
    return (f"CAST(COALESCE((SELECT SUM(v.value) {votes}),0) AS BIGINT) AS vote_score,"
            f"COALESCE((SELECT v.value {votes} AND v.account_id=:viewer),0) AS my_vote")


def save_document(db, account, data, *, kind="document", allow_empty_source=False):
    if account is None:
        raise accounts.SignInRequired
    title, markdown = data.get("title"), data.get("markdown")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        raise ValueError("Enter a document title of up to 160 characters.")
    if not isinstance(markdown, str) or len(markdown) > 100_000:
        raise ValueError("Use up to 100,000 characters of Markdown.")
    source_url = data.get("source_url")
    if "source_url" in data and not (allow_empty_source and source_url == ""):
        source_url = validate_news_source(source_url)
    if kind == "discussion" and source_url:
        raise ValueError("Discussion posts contain a title and text.")
    scheduled = data.get("scheduled_at", UNSET)
    if scheduled is not UNSET:
        if kind != "discussion":
            raise ValueError("Choose a discussion to schedule.")
        scheduled = schedule_value(scheduled)
    from . import document_context

    document_id = data.get("document_id")
    if document_id is None:
        document_id = db.execute(
            "INSERT INTO documents(title,markdown,audience,owner_id,source_url,kind,scheduled_at) VALUES (?,?,?,?,?,?,?) RETURNING id",
            (title.strip(), markdown, validate_audience(data.get("audience", "owner")), account["id"], source_url or "",
             kind, None if scheduled is UNSET else scheduled),
        ).fetchone()[0]
    elif type(document_id) is not int:
        raise ValueError("Choose a document.")
    else:
        existing = db.execute("SELECT owner_id,revision,audience,kind,scheduled_at FROM documents WHERE id=?", (document_id,)).fetchone()
        if not existing or existing["kind"] != kind or not is_owner(db, account, existing["owner_id"]):
            raise AccessDenied
        expected = data.get("revision")
        if expected is not None and (type(expected) is not int or existing["revision"] != expected):
            raise EditConflict("This document changed. Reload it before saving.")
        db.execute(
            "UPDATE documents SET title=?,markdown=?,audience=?,source_url=COALESCE(?,source_url),"
            "scheduled_at=?,updated=CURRENT_TIMESTAMP,revision=revision+1 WHERE id=?",
            (title.strip(), markdown, validate_audience(data.get("audience", existing["audience"])), source_url,
             existing["scheduled_at"] if scheduled is UNSET else scheduled, document_id),
        )
    document_context.save(db, account, document_id, data, kind=kind)
    set_recipients(db, "document", document_id, data.get("recipients"))
    if kind == "document":
        db.execute("""
            INSERT INTO document_versions(document_id,revision,title,markdown,source_url,author,saved)
            SELECT d.id,d.revision,d.title,d.markdown,d.source_url,a.username,d.updated
            FROM documents d JOIN accounts a ON a.id=? WHERE d.id=?
        """, (account["id"], document_id))
    return document_id
