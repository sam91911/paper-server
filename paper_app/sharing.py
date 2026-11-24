"""Account-based access to PDFs and Markdown documents."""

from . import accounts

AUDIENCES = ("owner", "users", "local", "all", "ai")
GRANTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS item_grants (
    kind TEXT NOT NULL CHECK (kind IN ('paper','document','comment','skill')),
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
       OR EXISTS (SELECT 1 FROM item_grants g WHERE g.kind='{kind}'
                  AND g.item_id={item_id} AND g.account_id=:viewer))))"""


PAPER_SCOPE = f"""
    WITH RECURSIVE visible_papers AS (
        SELECT p.*, access.owner_id, access.audience
        FROM papers p LEFT JOIN paper_access access ON access.paper_id=p.id
        WHERE (owner_id IS NULL AND :role = 'user') OR {access_sql('owner_id', 'audience', 'paper', 'p.id')}
    ), visible_documents AS (
        SELECT d.* FROM documents d WHERE {access_sql("d.owner_id", "d.audience", "document", "d.id")}
    )
"""


def initialize(db):
    grants_sql, = db.execute("SELECT sql FROM sqlite_schema WHERE name='item_grants'").fetchone()
    if "'skill'" not in grants_sql:
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
    if "revision" not in {row["name"] for row in db.execute("PRAGMA table_info(documents)")}:
        db.execute("ALTER TABLE documents ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")


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


def paper_for(db, paper_id, account, *, owner_only=False):
    row = db.execute(
        PAPER_SCOPE + "SELECT * FROM visible_papers WHERE id=:paper",
        viewer_params(account, paper=paper_id),
    ).fetchone()
    if row is None or (owner_only and row["owner_id"] is not None and not is_owner(db, account, row["owner_id"])):
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


def document_for(db, account, document_id):
    return db.execute(
        "SELECT * FROM documents d WHERE id=:document AND " + access_sql("d.owner_id", "d.audience", "document", "d.id"),
        viewer_params(account, document=document_id),
    ).fetchone()


def documents_for(db, account, *, targets_only=False, summaries=False):
    if targets_only:
        return [dict(row) for row in db.execute(
            "SELECT id,title FROM documents d WHERE " + access_sql("d.owner_id", "d.audience", "document", "d.id") + " ORDER BY title",
            viewer_params(account),
        )]
    columns = "d.id,d.owner_id,d.audience,d.title,d.updated,d.revision" if summaries else "d.*"
    items = [dict(row) for row in db.execute(
        f"SELECT {columns}, a.username AS owner_name, {accounts.ROLE_SQL.format(alias='a')} AS owner_role "
        "FROM documents d JOIN accounts a ON a.id=d.owner_id WHERE "
        + access_sql("d.owner_id", "d.audience", "document", "d.id") + " ORDER BY d.updated DESC, d.id DESC",
        viewer_params(account),
    )]
    return attach_recipients(db, "document", items, account)


def save_document(db, account, data):
    if account is None:
        raise accounts.SignInRequired
    title, markdown = data.get("title"), data.get("markdown")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        raise ValueError("Enter a document title of up to 160 characters.")
    if not isinstance(markdown, str) or len(markdown) > 100_000:
        raise ValueError("Use up to 100,000 characters of Markdown.")
    audience = validate_audience(data.get("audience", "owner"))
    values = title.strip(), markdown, audience
    document_id = data.get("document_id")
    if document_id is None:
        document_id = db.execute(
            "INSERT INTO documents(title,markdown,audience,owner_id) VALUES (?,?,?,?) RETURNING id",
            (*values, account["id"]),
        ).fetchone()[0]
    elif type(document_id) is not int:
        raise ValueError("Choose a document.")
    else:
        existing = db.execute("SELECT owner_id,revision FROM documents WHERE id=?", (document_id,)).fetchone()
        if not existing or not is_owner(db, account, existing["owner_id"]):
            raise AccessDenied
        expected = data.get("revision")
        if expected is not None and (type(expected) is not int or existing["revision"] != expected):
            raise EditConflict("This document changed. Reload it before saving.")
        db.execute(
            "UPDATE documents SET title=?,markdown=?,audience=?,updated=CURRENT_TIMESTAMP,revision=revision+1 "
            "WHERE id=?", (*values, document_id),
        )
    set_recipients(db, "document", document_id, data.get("recipients"))
    return document_id
