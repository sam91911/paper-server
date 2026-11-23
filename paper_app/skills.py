"""Owned Markdown skills with account-based sharing and search."""

import json
import re

from . import sharing

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES accounts(id),
    audience TEXT NOT NULL CHECK (audience IN ('owner', 'users', 'local', 'all', 'ai')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    markdown TEXT NOT NULL,
    tags TEXT NOT NULL,
    search_text TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skill_tags (
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (skill_id,tag)
);
CREATE INDEX IF NOT EXISTS skill_tags_search ON skill_tags(tag,skill_id);
"""

SUMMARY = "s.id,s.owner_id,s.audience,s.title,s.description,s.tags,s.archived,s.revision,s.created,s.updated"
ACCESS = sharing.access_sql("s.owner_id", "s.audience", "skill", "s.id")
PAGE_SIZE = 50
MAX_ID = 2**63 - 1


def text(value, label, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or (required and not value.strip()):
        raise ValueError(f"Use {label} of up to {limit:,} characters.")
    return value


def query_id(value, *, optional=False):
    if optional and value in ("", "0"):
        return 0
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > MAX_ID:
        raise ValueError("Choose a valid skill ID or page cursor.")
    return int(value)


def result(row):
    skill = dict(row)
    skill["tags"] = json.loads(skill["tags"])
    skill["archived"] = bool(skill["archived"])
    return skill


def list_skills(db, account, *, query="", tag="", after=0, archived=False):
    query = text(query, "a search query", 200).strip().casefold()
    tag = text(tag, "a tag", 40).strip().casefold()
    escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    scope = "s.archived=1 AND s.owner_id=:viewer" if archived else f"s.archived=0 AND {ACCESS}"
    rows = db.execute(
        f"SELECT {SUMMARY} FROM skills s WHERE {scope} AND s.id>:after "
        "AND s.search_text LIKE :pattern ESCAPE '!' "
        "AND (:tag='' OR EXISTS (SELECT 1 FROM skill_tags t WHERE t.skill_id=s.id AND t.tag=:tag)) "
        "ORDER BY s.id LIMIT :limit",
        sharing.viewer_params(account, after=after, pattern=f"%{escaped}%", tag=tag, limit=PAGE_SIZE + 1),
    ).fetchall()
    return {
        "skills": [result(row) for row in rows[:PAGE_SIZE]],
        "next_after": rows[PAGE_SIZE - 1]["id"] if len(rows) > PAGE_SIZE else None,
    }


def detail(db, account, skill_id):
    row = db.execute(
        f"SELECT {SUMMARY},s.markdown FROM skills s WHERE s.id=:id AND {ACCESS} "
        "AND (s.archived=0 OR s.owner_id=:viewer)",
        sharing.viewer_params(account, id=skill_id),
    ).fetchone()
    if row is None:
        raise LookupError("Skill unavailable.")
    return sharing.attach_recipients(db, "skill", [result(row)], account)[0]


def save(db, account, data):
    action = data.get("action", "create")
    if action not in ("create", "update", "archive", "restore"):
        raise ValueError("Choose create, update, archive, or restore.")
    owner = account["id"]
    if action == "create":
        if "id" in data or "revision" in data:
            raise ValueError("A new skill does not take an ID or revision.")
        current = None
    else:
        skill_id, revision = data.get("id"), data.get("revision")
        if not all(type(value) is int and 0 < value <= MAX_ID for value in (skill_id, revision)):
            raise ValueError("Choose a skill and its current revision.")
        current = detail(db, account, skill_id)
        if current["owner_id"] != owner:
            raise sharing.AccessDenied
        if current["revision"] != revision:
            raise sharing.EditConflict("This skill has changed. Reload it and try again.")
        if action in ("archive", "restore"):
            archived = action == "archive"
            if current["archived"] != archived:
                db.execute(
                    "UPDATE skills SET archived=?,revision=revision+1,updated=CURRENT_TIMESTAMP WHERE id=?",
                    (int(archived), skill_id),
                )
            return detail(db, account, skill_id)
        if current["archived"]:
            raise sharing.EditConflict("Restore this skill before editing it.")

    title = text(data.get("title"), "a title", 160, required=True).strip()
    description = text(data.get("description", ""), "a description", 1000).strip()
    markdown = text(data.get("markdown"), "Markdown", 10_000, required=True)
    tags = data.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 20:
        raise ValueError("Use up to 20 tags.")
    normalized = {}
    for value in tags:
        tag = text(value, "a tag", 40, required=True).strip()
        normalized.setdefault(tag.casefold(), tag)
    search_text = "\n".join((title, description, *normalized.values())).casefold()
    audience = sharing.validate_audience(data.get("audience", current["audience"] if current else "owner"))
    fields = (title, description, markdown, json.dumps(list(normalized.values())), search_text, audience)
    if current is None:
        skill_id = db.execute(
            "INSERT INTO skills(title,description,markdown,tags,search_text,audience,owner_id) "
            "VALUES (?,?,?,?,?,?,?) RETURNING id", (*fields, owner),
        ).fetchone()[0]
    else:
        db.execute(
            "UPDATE skills SET title=?,description=?,markdown=?,tags=?,search_text=?,audience=?,"
            "updated=CURRENT_TIMESTAMP,revision=revision+1 WHERE id=?", (*fields, skill_id),
        )
        db.execute("DELETE FROM skill_tags WHERE skill_id=?", (skill_id,))
    db.executemany("INSERT INTO skill_tags VALUES (?,?)", ((skill_id, tag) for tag in normalized))
    sharing.set_recipients(db, "skill", skill_id, data.get("recipients"))
    return detail(db, account, skill_id)
