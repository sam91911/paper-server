"""Account-scoped API requests for workstation AI reviewers."""

import hashlib
import subprocess
from pathlib import Path

from paper_client import pdf_text

from . import accounts, library, sharing

REVIEW_TABLE = """
CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY,
    requester_id INTEGER NOT NULL REFERENCES accounts(id),
    agent_id INTEGER NOT NULL REFERENCES accounts(id),
    agent_role TEXT NOT NULL CHECK (agent_role IN ('local','cloud')),
    kind TEXT NOT NULL CHECK (kind IN ('paper','document','thread')),
    target_id INTEGER NOT NULL,
    position INTEGER,
    post INTEGER NOT NULL CHECK (post IN (0,1)),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','complete','failed','withdrawn')),
    response TEXT NOT NULL DEFAULT '',
    comment_id INTEGER REFERENCES comments(id),
    end_page INTEGER,
    whole_pdf INTEGER NOT NULL DEFAULT 0 CHECK (whole_pdf IN (0,1)),
    source_format TEXT NOT NULL DEFAULT 'pdf' CHECK (source_format IN ('pdf','text'))
);
"""
SCHEMA = REVIEW_TABLE.format(table="review_requests") + """
CREATE INDEX IF NOT EXISTS reviews_requester ON review_requests(requester_id,kind,target_id,id);
CREATE INDEX IF NOT EXISTS reviews_agent ON review_requests(agent_id,status,id);
"""

AI_ROLES = ("local", "cloud")
KINDS = ("paper", "document", "thread")
ACCOUNT_FIELDS = f"a.id,a.username,{accounts.ROLE_SQL.format(alias='a')} AS role"


def initialize(db):
    columns = {row["name"] for row in db.execute("PRAGMA table_info(review_requests)")}
    for name, definition in (
        ("end_page", "INTEGER"),
        ("whole_pdf", "INTEGER NOT NULL DEFAULT 0 CHECK (whole_pdf IN (0,1))"),
        ("source_format", "TEXT NOT NULL DEFAULT 'pdf' CHECK (source_format IN ('pdf','text'))"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE review_requests ADD COLUMN {name} {definition}")
    sql, = db.execute("SELECT sql FROM sqlite_schema WHERE name='review_requests'").fetchone()
    if "'withdrawn'" in sql:
        return
    db.execute(REVIEW_TABLE.format(table="new_review_requests"))
    db.execute("INSERT INTO new_review_requests SELECT * FROM review_requests")
    db.execute("DROP TABLE review_requests")
    db.execute("ALTER TABLE new_review_requests RENAME TO review_requests")
    db.execute("CREATE INDEX reviews_requester ON review_requests(requester_id,kind,target_id,id)")
    db.execute("CREATE INDEX reviews_agent ON review_requests(agent_id,status,id)")


def valid_id(value):
    return type(value) is int and 0 < value < 2**63


def eligible_agents(db, account, kind, target_id):
    if account["role"] in AI_ROLES:
        raise sharing.AccessDenied
    if kind not in KINDS or not valid_id(target_id):
        raise ValueError("Choose a review target.")
    target(db, account, kind, target_id, None)
    agents = []
    for agent in db.execute(
        f"SELECT {ACCOUNT_FIELDS},a.display_name FROM accounts a WHERE a.role='ai' "
        "AND a.disabled_at IS NULL AND a.ai_location IN ('local','cloud') ORDER BY a.ai_location DESC,a.username",
    ):
        try:
            target(db, agent, kind, target_id, None)
        except sharing.AccessDenied:
            continue
        agents.append({key: agent[key] for key in ("username", "display_name", "role")})
    return {"agents": agents}


def target(db, account, kind, target_id, position):
    if kind == "paper":
        if not sharing.paper_for(db, target_id, account, file_access=True)["sha256"]:
            raise sharing.AccessDenied
        result = {"paper_id": target_id}
        if position is not None:
            result["location"] = {"kind": "pdf", "id": target_id, "position": position}
        return result
    if kind == "document":
        if sharing.document_for(db, account, target_id) is None:
            raise sharing.AccessDenied
        result = {"document_id": target_id}
        if position is not None:
            result["location"] = {"kind": "document", "id": target_id, "position": position}
            library.comment_target(db, account, result["location"])
        return result

    row = db.execute("SELECT paper_id,document_id FROM comments WHERE id=?", (target_id,)).fetchone()
    if not row:
        raise sharing.AccessDenied
    paper_id, document_id = row
    if paper_id is not None:
        sharing.paper_for(db, paper_id, account)
        if db.execute("SELECT 1 FROM archived_papers WHERE paper_id=?", (paper_id,)).fetchone():
            raise sharing.AccessDenied
    elif sharing.document_for(db, account, document_id) is None:
        raise sharing.AccessDenied
    if not library.can_reply(db, paper_id, target_id, account, document_id):
        raise sharing.AccessDenied
    return {"paper_id": paper_id, "document_id": document_id, "parent_id": target_id}


def check_access(db, row):
    requester = db.execute(f"SELECT {ACCOUNT_FIELDS} FROM accounts a WHERE id=?", (row["requester_id"],)).fetchone()
    agent = db.execute(f"SELECT {ACCOUNT_FIELDS} FROM accounts a WHERE id=?", (row["agent_id"],)).fetchone()
    if agent["role"] != row["agent_role"] or requester["role"] in AI_ROLES:
        raise sharing.AccessDenied
    args = row["kind"], row["target_id"], row["position"]
    target(db, requester, *args)
    return target(db, agent, *args)


def summary(row):
    return {
        "id": row["id"], "kind": row["kind"], "target_id": row["target_id"],
        "position": row["position"], "post": bool(row["post"]), "status": row["status"],
        "response": row["response"], "comment_id": row["comment_id"],
        "agent": row["agent"], "agent_role": row["agent_role"],
        **({"end_page": row["end_page"], "whole_pdf": bool(row["whole_pdf"]), "source_format": row["source_format"]}
           if row["kind"] == "paper" else {}),
    }


def query_rows(db, condition, parameters, *, pending=False):
    limit = "" if pending else " LIMIT 30"
    order = "ASC" if pending else "DESC"
    return db.execute(
        "SELECT r.*, a.username AS agent FROM review_requests r JOIN accounts a ON r.agent_id=a.id "
        f"WHERE {condition} ORDER BY r.id {order}{limit}", parameters,
    )


def thread_context(db, comment_id):
    return [dict(row) for row in db.execute(
        "WITH RECURSIVE parents AS ("
        " SELECT id,parent_id,body,deleted,0 AS depth FROM comments WHERE id=?"
        " UNION ALL SELECT c.id,c.parent_id,c.body,c.deleted,p.depth+1 FROM comments c"
        " JOIN parents p ON c.id=p.parent_id"
        ") SELECT id,substr(body,1,4000) AS body FROM parents WHERE deleted=0 ORDER BY depth LIMIT 8",
        (comment_id,),
    )]


def check_read_access(db, account, row, *, is_agent):
    if not is_agent and row["status"] in ("pending", "withdrawn"):
        target(db, account, row["kind"], row["target_id"], row["position"])
    else:
        check_access(db, row)


def read(db, account, *, review_id=None, kind=None, target_id=None):
    is_agent = account["role"] in AI_ROLES
    scope = "r.agent_id=?" if is_agent else "r.requester_id=?"
    params = (account["id"],)
    if review_id is not None:
        row = query_rows(db, scope + " AND r.id=?", (*params, review_id)).fetchone()
        if row is None:
            raise LookupError("Review unavailable.")
        try:
            check_read_access(db, account, row, is_agent=is_agent)
        except (sharing.AccessDenied, ValueError):
            raise LookupError("Review unavailable.") from None
        result = summary(row)
        if is_agent and row["kind"] == "thread" and row["status"] == "pending":
            result["thread"] = thread_context(db, row["target_id"])
        return {"review": result}
    if kind is not None or target_id is not None:
        if kind not in KINDS or not valid_id(target_id):
            raise ValueError("Choose a review target.")
        scope += " AND r.kind=? AND r.target_id=?"
        params += (kind, target_id)
    if is_agent:
        scope += " AND r.status='pending'"
    results = []
    for row in query_rows(db, scope, params, pending=is_agent):
        try:
            check_read_access(db, account, row, is_agent=is_agent)
        except (sharing.AccessDenied, ValueError):
            continue
        results.append(summary(row))
        if len(results) == 30:
            break
    return {"reviews": results}


def verified_pdf(db, account, paper_id):
    paper = sharing.paper_for(db, paper_id, account, file_access=True)
    try:
        with Path(paper["path"]).open("rb") as source:
            payload = source.read(pdf_text.PDF_LIMIT + 1)
    except OSError:
        raise ValueError("The local PDF is unavailable. Re-import it to restore access.") from None
    if (len(payload) > pdf_text.PDF_LIMIT or b"%PDF-" not in payload[:1024]
        or hashlib.sha256(payload).hexdigest() != paper["sha256"]):
        raise ValueError("Re-import the verified PDF before reviewing it.")
    return payload


def read_pdf_text(db, account, review_id):
    row = query_rows(db, "r.id=? AND r.agent_id=? AND r.agent_role=? AND r.kind='paper' "
                     "AND r.status='pending' AND r.source_format='text'",
                     (review_id, account["id"], account["role"])).fetchone()
    if row is None:
        raise LookupError("Review unavailable.")
    check_access(db, row)
    payload = verified_pdf(db, account, row["target_id"])
    try:
        return {"text": pdf_text.extract(payload, row["position"], row["end_page"])}
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Could not extract text from the verified PDF with Poppler.") from None


def create(db, account, data):
    if account["role"] in AI_ROLES:
        raise sharing.AccessDenied
    kind, target_id = data.get("kind"), data.get("target_id")
    position, post = data.get("position"), data.get("post", False)
    if kind not in KINDS or not valid_id(target_id) or type(post) is not bool:
        raise ValueError("Choose a review target.")
    if position is not None and (kind == "thread" or type(position) is not int or not 0 < position <= 1_000_000):
        raise ValueError("Choose a positive PDF page or document line.")
    end_page = data.get("end_page")
    whole_pdf = data.get("whole_pdf", False)
    source_format = data.get("source_format", "pdf")
    if type(whole_pdf) is not bool or source_format not in ("pdf", "text"):
        raise ValueError("Choose a valid PDF scope and source format.")
    if kind != "paper" and (end_page is not None or whole_pdf or source_format != "pdf"):
        raise ValueError("PDF options apply only to paper reviews.")
    if whole_pdf and (position is not None or end_page is not None):
        raise ValueError("Choose either the whole PDF or specific pages.")
    if kind == "paper" and not whole_pdf:
        position = position or 1
        if end_page is not None:
            if type(end_page) is not int or not position <= end_page <= 1_000_000:
                raise ValueError("The last PDF page must be at or after the first page.")
            if end_page == position:
                end_page = None
    username = accounts.identity(data.get("agent"))
    agent = db.execute(f"SELECT {ACCOUNT_FIELDS} FROM accounts a WHERE username=? AND a.disabled_at IS NULL",
                       (username,)).fetchone()
    if not agent or agent["role"] not in AI_ROLES:
        raise ValueError("Choose a Local AI or Cloud AI account.")
    if agent["role"] != data.get("agent_role"):
        raise ValueError("Choose the assigned AI account's role.")
    target(db, account, kind, target_id, position)
    try:
        target(db, agent, kind, target_id, position)
    except sharing.AccessDenied:
        raise ValueError("Share the review target and its sources with the assigned AI account first.") from None
    if kind == "paper" and not whole_pdf and (end_page is not None or source_format == "text"):
        payload = verified_pdf(db, account, target_id)
        try:
            count = pdf_text.page_count(payload)
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Could not read the PDF page count with Poppler.") from None
        if (end_page or position) > count:
            raise ValueError(f"This PDF has {count} page(s).")
    pending = db.execute(
        "SELECT id FROM review_requests WHERE requester_id=? AND agent_id=? AND agent_role=? "
        "AND kind=? AND target_id=? AND position IS NOT DISTINCT FROM ? AND post=? AND status='pending' "
        "AND end_page IS NOT DISTINCT FROM ? AND whole_pdf=? AND source_format=? "
        "ORDER BY id DESC LIMIT 1",
        (account["id"], agent["id"], agent["role"], kind, target_id, position, int(post), end_page, int(whole_pdf), source_format),
    ).fetchone()
    if pending:
        return read(db, account, review_id=pending["id"])
    review_id = db.execute(
        "INSERT INTO review_requests(requester_id,agent_id,agent_role,kind,target_id,position,post,end_page,whole_pdf,source_format)"
        " VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
        (account["id"], agent["id"], agent["role"], kind, target_id, position, int(post), end_page, int(whole_pdf), source_format),
    ).fetchone()[0]
    return read(db, account, review_id=review_id)


def withdraw(db, account, data):
    review_id = data.get("id")
    if not valid_id(review_id):
        raise ValueError("Choose a review to withdraw.")
    row = query_rows(db, "r.id=? AND r.requester_id=?", (review_id, account["id"])).fetchone()
    if row is None or account["role"] in AI_ROLES:
        raise LookupError("Review unavailable.")
    if row["status"] == "withdrawn":
        return {"review": summary(row)}
    if row["status"] != "pending":
        raise sharing.EditConflict("Only pending reviews can be withdrawn.")
    db.execute("UPDATE review_requests SET status='withdrawn' WHERE id=?", (review_id,))
    return {"review": {**summary(row), "status": "withdrawn"}}


def complete(db, account, data):
    review_id = data.get("id")
    status, response = data.get("status"), data.get("response")
    if not valid_id(review_id) or status not in ("complete", "failed"):
        raise ValueError("Choose a review and its outcome.")
    if not isinstance(response, str) or not response.strip() or len(response) > 20_000 or "\x00" in response:
        raise ValueError("Provide a review response of up to 20,000 characters.")
    row = query_rows(db, "r.id=? AND r.agent_id=? AND r.agent_role=?",
                     (review_id, account["id"], account["role"])).fetchone()
    if row is None:
        raise LookupError("Review unavailable.")
    if row["status"] == "withdrawn":
        raise sharing.EditConflict("This review was withdrawn.")
    comment = check_access(db, row)
    response = response.strip()
    if row["status"] != "pending":
        if (row["status"], row["response"]) != (status, response):
            raise sharing.EditConflict("This review already has a result.")
        return {"review": summary(row)}
    comment_id = None
    if status == "complete" and row["post"]:
        comment_id = library.save_comment(db, comment.pop("paper_id", None), response, account, **comment)
    db.execute("UPDATE review_requests SET status=?,response=?,comment_id=? WHERE id=?",
               (status, response, comment_id, review_id))
    return read(db, account, review_id=review_id)
