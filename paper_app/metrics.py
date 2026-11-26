"""Revisioned corrections and per-metric editor grants."""

import math
import re

from . import accounts, sharing

FIELDS = ("page", "metric", "value", "unit", "conditions", "evidence")
COLUMNS = "m.paper_id," + ",".join(f"COALESCE(c.{field},m.{field}) AS {field}" for field in FIELDS)
LATEST = (" LEFT JOIN metric_corrections c ON c.metric_id=m.cursor_id AND c.revision=("
          "SELECT MAX(revision) FROM metric_corrections WHERE metric_id=m.cursor_id) ")
ACTIVE = "COALESCE(c.removed,0)=0"
REMOVED_COLUMN = "INTEGER NOT NULL DEFAULT 0 CHECK (removed IN (0,1))"
PAGE_SIZE = 50
SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS metric_corrections (
        metric_id INTEGER NOT NULL REFERENCES metrics(cursor_id),
        revision INTEGER NOT NULL,
        editor_id INTEGER NOT NULL REFERENCES accounts(id),
        page INTEGER NOT NULL, metric TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL,
        conditions TEXT NOT NULL, evidence TEXT NOT NULL, reason TEXT NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        removed {REMOVED_COLUMN},
        PRIMARY KEY (metric_id,revision)
    )""",
    """CREATE TABLE IF NOT EXISTS metric_editors (
        metric_id INTEGER NOT NULL REFERENCES metrics(cursor_id),
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        PRIMARY KEY (metric_id,account_id)
    )""",
)


def identifier(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("Choose a valid metric, paper, or revision ID.")
    return value


def paper_for(db, account, paper_id):
    paper = sharing.paper_for(db, paper_id, account, file_access=True)
    if db.execute("SELECT 1 FROM archived_papers WHERE paper_id=?", (paper_id,)).fetchone():
        raise sharing.AccessDenied
    return paper


def metric_for(db, account, metric_id):
    row = db.execute("SELECT * FROM metrics WHERE cursor_id=?", (metric_id,)).fetchone()
    if row is None:
        raise sharing.AccessDenied
    return row, paper_for(db, account, row["paper_id"])


def can_edit_all(db, paper, account):
    if paper["owner_id"] is None:
        return account["role"] == "user"
    return sharing.is_owner(db, account, paper["owner_id"])


def retain_detections(db, paper_id, rows):
    if paper_id is None:
        return rows
    # Keyword changes can rename a candidate. Match removed readings by their
    # extracted source data so a different label cannot bring them back.
    removed = {tuple(row) for row in db.execute(
        "SELECT m.page,m.value,m.unit,m.conditions,m.evidence "
        f"FROM metrics m{LATEST}WHERE m.paper_id=? AND c.removed=1", (paper_id,),
    )}
    return [row for row in rows if (row[0], *row[2:]) not in removed]


def list_metrics(db, account, paper_id, after, *, removed=False):
    paper = paper_for(db, account, paper_id)
    can_edit = can_edit_all(db, paper, account)
    owner = paper["owner_id"] is not None and can_edit
    rows = db.execute(
        f"SELECT m.cursor_id AS id,{COLUMNS},COALESCE(c.revision,1) AS revision,COALESCE(c.removed,0) AS removed,"
        "EXISTS(SELECT 1 FROM metric_editors e WHERE e.metric_id=m.cursor_id AND e.account_id=?) AS granted "
        f"FROM metrics m{LATEST}WHERE m.paper_id=? AND m.cursor_id>? "
        "AND COALESCE(c.removed,0)=? ORDER BY m.cursor_id LIMIT ?",
        (account["id"], paper_id, after, int(removed), PAGE_SIZE + 1),
    ).fetchall()
    items = []
    for row in rows[:PAGE_SIZE]:
        item = dict(row)
        item["removed"] = bool(item["removed"])
        item["can_edit"] = bool(item.pop("granted") or can_edit)
        items.append(item)
    return {"metrics": items, "can_manage_editors": owner, "can_claim_paper": paper["owner_id"] is None and can_edit,
            "next_after": items[-1]["id"] if len(rows) > PAGE_SIZE else None}


def history(db, account, metric_id, before=None):
    original, paper = metric_for(db, account, metric_id)
    rows = db.execute(
        "SELECT c.revision,c.page,c.metric,c.value,c.unit,c.conditions,c.evidence,c.reason,c.created,c.removed,a.username AS editor "
        "FROM metric_corrections c JOIN accounts a ON a.id=c.editor_id "
        "WHERE c.metric_id=? AND c.revision<? ORDER BY c.revision DESC LIMIT ?",
        (metric_id, before or 2**63 - 1, PAGE_SIZE + 1),
    ).fetchall()
    result = {"original": {field: original[field] for field in FIELDS},
              "corrections": [dict(row, removed=bool(row["removed"])) for row in rows[:PAGE_SIZE]],
              "next_before": rows[PAGE_SIZE - 1]["revision"] if len(rows) > PAGE_SIZE else None}
    if sharing.is_owner(db, account, paper["owner_id"]):
        result["editors"] = [row[0] for row in db.execute(
            "SELECT a.username FROM metric_editors e JOIN accounts a ON a.id=e.account_id "
            "WHERE e.metric_id=? ORDER BY a.username", (metric_id,),
        )]
    return result


def correction_text(data, field, limit, *, required=False):
    value = data.get(field)
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or (required and not value.strip()):
        raise ValueError(f"Enter a {field} of up to {limit:,} characters.")
    return value.strip()


def correct(db, account, data):
    metric_id = identifier(data.get("metric_id"))
    revision = identifier(data.get("revision"))
    original, paper = metric_for(db, account, metric_id)
    if not (can_edit_all(db, paper, account) or db.execute(
        "SELECT 1 FROM metric_editors WHERE metric_id=? AND account_id=?", (metric_id, account["id"]),
    ).fetchone()):
        raise sharing.AccessDenied
    latest = db.execute("SELECT * FROM metric_corrections WHERE metric_id=? ORDER BY revision DESC LIMIT 1",
                        (metric_id,)).fetchone()
    if (latest["revision"] if latest else 1) != revision:
        raise sharing.EditConflict("This metric changed. Reload it before saving.")
    base = latest or original
    was_removed = bool(latest and latest["removed"])
    action = data.get("action", "correct")
    reason = correction_text(data, "reason", 2000, required=True)
    if action not in ("correct", "remove", "restore"):
        raise ValueError("Choose correct, remove, or restore.")
    if was_removed != (action == "restore"):
        raise ValueError("This metric is removed. Restore it first." if was_removed else "This metric is active.")
    if action != "correct":
        if any(field in data for field in FIELDS):
            raise ValueError("Remove or restore the metric before changing its fields.")
        updated = {field: base[field] for field in FIELDS}
    else:
        updated = corrected_fields(base, data)
    removed = action == "remove"
    db.execute(
        "INSERT INTO metric_corrections(metric_id,revision,editor_id,page,metric,value,unit,conditions,evidence,reason,removed)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (metric_id, revision + 1, account["id"], *(updated[field] for field in FIELDS), reason, int(removed)),
    )
    return {"metric_id": metric_id, "revision": revision + 1, "removed": removed}


def corrected_fields(base, data):
    updated = {field: base[field] for field in FIELDS}
    if "page" in data:
        updated["page"] = identifier(data["page"])
    for field, limit in (("metric", 500), ("value", 100), ("unit", 200), ("conditions", 20_000), ("evidence", 50_000)):
        if field in data and data[field] != base[field]:
            updated[field] = correction_text(data, field, limit, required=field in ("metric", "value"))
    value = updated["value"]
    if value != base["value"] and (
        not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value)
        or not math.isfinite(float(value))
    ):
        raise ValueError("Enter a finite decimal value.")
    if all(updated[field] == base[field] for field in FIELDS):
        raise ValueError("Change at least one metric field.")
    return updated


def set_editor(db, account, data):
    metric_id = identifier(data.get("metric_id"))
    _, paper = metric_for(db, account, metric_id)
    if not sharing.is_owner(db, account, paper["owner_id"]):
        raise sharing.AccessDenied
    action = data.get("action")
    if action not in ("grant", "revoke"):
        raise ValueError("Choose grant or revoke.")
    username = accounts.identity(data.get("username"))
    editor = db.execute("SELECT id FROM accounts WHERE username=?", (username,)).fetchone()
    if editor is None or editor["id"] in (account["id"], paper["owner_id"]):
        raise ValueError("Choose another existing account.")
    if action == "grant":
        db.execute("INSERT INTO metric_editors VALUES (?,?) ON CONFLICT DO NOTHING", (metric_id, editor["id"]))
    else:
        db.execute("DELETE FROM metric_editors WHERE metric_id=? AND account_id=?", (metric_id, editor["id"]))


def claim_paper(db, account, paper_id):
    paper = paper_for(db, account, identifier(paper_id))
    if account["role"] != "user" or paper["owner_id"] is not None:
        raise sharing.AccessDenied
    db.execute("INSERT INTO paper_access(paper_id,owner_id,audience) VALUES (?,?,'users')", (paper_id, account["id"]))
