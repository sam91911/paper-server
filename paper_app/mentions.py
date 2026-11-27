"""Resolve usernames in saved content and list mentions with current access checks."""

import re

from . import sharing

USERNAME_MENTION = re.compile(r"(?<![A-Za-z0-9_.+@-])@([A-Za-z0-9][A-Za-z0-9_.-]{1,31})(?![A-Za-z0-9_.-])")
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS comment_mentions (
        comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        PRIMARY KEY(account_id,comment_id)
    )""",
    """CREATE TABLE IF NOT EXISTS document_mentions (
        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        PRIMARY KEY(account_id,document_id)
    )""",
    "CREATE INDEX IF NOT EXISTS comment_mentions_content ON comment_mentions(comment_id)",
    "CREATE INDEX IF NOT EXISTS document_mentions_content ON document_mentions(document_id)",
)


def sync(db, kind, content_id, author_id, content):
    names = {match.lower() for match in USERNAME_MENTION.findall(content)}
    table, field = {"comment": ("comment_mentions", "comment_id"),
                    "document": ("document_mentions", "document_id")}[kind]
    db.execute(f"DELETE FROM {table} WHERE {field}=?", (content_id,))
    candidates = sorted(names | {name.rstrip(".") for name in names})
    accounts = {}
    for start in range(0, len(candidates), 200):
        batch = candidates[start:start + 200]
        placeholders = ",".join("?" for _ in batch)
        accounts.update((row[0], row[1]) for row in db.execute(
            f"SELECT LOWER(username),id FROM accounts WHERE disabled_at IS NULL AND LOWER(username) IN ({placeholders})",
            batch))
    recipients = {accounts.get(name, accounts.get(name.rstrip("."))) for name in names}
    db.executemany(f"INSERT INTO {table}({field},account_id) VALUES (?,?)",
                   ((content_id, recipient) for recipient in recipients - {None, author_id}))


def inbox(db, account):
    from . import library

    rows = db.execute(sharing.PAPER_SCOPE + """
        SELECT 'comment' AS item_kind,c.id AS id,c.paper_id,c.document_id,c.updated AS updated,SUBSTR(c.body,1,500) AS body,
               d.kind AS document_kind,d.source_url,COALESCE(d.title,NULLIF(p.title,''),'Paper') AS title,
               a.username AS author
        FROM comment_mentions m JOIN comments c ON c.id=m.comment_id
        LEFT JOIN visible_papers p ON p.id=c.paper_id
        LEFT JOIN visible_documents d ON d.id=c.document_id
        LEFT JOIN comment_authors ca ON ca.comment_id=c.id LEFT JOIN accounts a ON a.id=ca.account_id
        WHERE m.account_id=:viewer AND c.deleted=0 AND
          (d.id IS NOT NULL OR (p.id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM archived_papers x WHERE x.paper_id=p.id)))
        UNION ALL
        SELECT 'document',d.id,NULL,d.id,d.updated,SUBSTR(d.markdown,1,500),d.kind,d.source_url,d.title,a.username
        FROM document_mentions m JOIN visible_documents d ON d.id=m.document_id
        JOIN accounts a ON a.id=d.owner_id WHERE m.account_id=:viewer
        ORDER BY updated DESC,id DESC,item_kind
        """, sharing.viewer_params(account))
    result = []
    for row in rows:
        comment = row["item_kind"] == "comment"
        if comment and not library.can_reply(db, row["paper_id"], row["id"], account, row["document_id"]):
            continue
        if row["paper_id"] is not None:
            url = f"/papers?paper={row['paper_id']}"
        else:
            page = "discussions" if row["document_kind"] == "discussion" else "news" if row["source_url"] else "documents"
            url = f"/{page}?document={row['document_id']}"
        if comment:
            url += f"&comment={row['id']}#comment-{row['id']}"
        result.append({"kind": row["item_kind"], "id": row["id"], "title": row["title"],
                       "author": row["author"], "updated": row["updated"], "url": url,
                       "excerpt": " ".join(row["body"].split())[:240]})
        if len(result) == 50:
            break
    return {"mentions": result}
