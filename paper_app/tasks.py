"""Tasks shared between their creators and assignees."""

import re
from datetime import date

from . import accounts, findings, sharing

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES accounts(id),
    assignee_id INTEGER REFERENCES accounts(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','closed')),
    due_on TEXT,
    issue_url TEXT,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner_id);
CREATE INDEX IF NOT EXISTS tasks_assignee ON tasks(assignee_id);
"""
STATUSES = ("open", "in_progress", "closed")


def read(db, account):
    owner = sharing.owner_sql("t.owner_id")
    return {"tasks": [dict(row, can_manage=bool(row["can_manage"])) for row in db.execute(f"""
        SELECT t.*, o.username AS creator, a.username AS assignee, {owner} AS can_manage
        FROM tasks t JOIN accounts o ON o.id=t.owner_id
        LEFT JOIN accounts a ON a.id=t.assignee_id
        WHERE {owner} OR t.assignee_id=:viewer
        ORDER BY CASE WHEN t.status='closed' THEN 1 ELSE 0 END,
                 CASE WHEN t.due_on IS NULL THEN 1 ELSE 0 END, t.due_on, t.id DESC
    """, sharing.viewer_params(account))]}


def update(db, account, data):
    task_id = data.get("id")
    viewer = account["id"]
    status = data.get("status", "open")
    if status not in STATUSES:
        raise ValueError("Choose a task status.")

    if task_id is not None:
        existing = db.execute("SELECT * FROM tasks WHERE id=?", (findings.positive_id(task_id),)).fetchone()
        if not existing:
            raise sharing.AccessDenied
        owner = sharing.is_owner(db, account, existing["owner_id"])
        if not owner and viewer != existing["assignee_id"]:
            raise sharing.AccessDenied
        revision = data.get("revision")
        if type(revision) is not int or existing["revision"] != revision:
            raise sharing.EditConflict("This task changed. Reload it before saving.")
        status = data.get("status", existing["status"])
        if not owner:
            db.execute("UPDATE tasks SET status=?,revision=revision+1 WHERE id=?", (status, task_id))
            return {"id": task_id}

    def field(name, default):
        return data.get(name, default if task_id is None else existing[name])

    title = field("title", "")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        raise ValueError("Enter a task title of up to 160 characters.")
    description = field("description", "")
    if not isinstance(description, str) or len(description) > 10000:
        raise ValueError("Enter up to 10,000 characters of description.")
    due_on = field("due_on", None)
    if due_on is not None:
        if not isinstance(due_on, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", due_on):
            raise ValueError("Choose a deadline date or clear it.")
        date.fromisoformat(due_on)
    issue_url = field("issue_url", None)
    if issue_url is not None and (not isinstance(issue_url, str) or len(issue_url) > 512 or not re.fullmatch(
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*", issue_url
    )):
        raise ValueError("Enter the HTTPS URL of a GitHub issue or clear it.")
    assignee_id = None if task_id is None else existing["assignee_id"]
    if "assignee" in data:
        assignee_id = None
        if data["assignee"] is not None:
            username = accounts.identity(data["assignee"])
            row = db.execute("SELECT id FROM accounts WHERE LOWER(username)=LOWER(?) AND disabled_at IS NULL",
                             (username,)).fetchone()
            if row is None:
                raise ValueError("Choose an active account as assignee.")
            assignee_id = row["id"]
    values = (title.strip(), description, status, due_on, issue_url, assignee_id)
    if task_id is None:
        task_id = db.execute("""
            INSERT INTO tasks(title,description,status,due_on,issue_url,assignee_id,owner_id)
            VALUES (?,?,?,?,?,?,?) RETURNING id
        """, (*values, viewer)).fetchone()[0]
    else:
        db.execute("""
            UPDATE tasks SET title=?,description=?,status=?,due_on=?,issue_url=?,assignee_id=?,revision=revision+1
            WHERE id=?
        """, (*values, task_id))
    return {"id": task_id}
