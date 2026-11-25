"""Access-aware links from documents to research and agent goals."""

from . import agent_goals, findings, goals, sharing


SCHEMA = """
CREATE TABLE IF NOT EXISTS document_contexts (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    topic TEXT NOT NULL DEFAULT '',
    research_goal_id INTEGER REFERENCES research_goals(id),
    agent_goal_id INTEGER REFERENCES agent_goals(id),
    CHECK (research_goal_id IS NULL OR agent_goal_id IS NULL)
)
"""
JOIN = " LEFT JOIN document_contexts dc ON dc.document_id=d.id"
COLUMNS = "COALESCE(dc.topic,'') AS topic,dc.research_goal_id,dc.agent_goal_id"


def options(db, account):
    result = []
    for row in db.execute("SELECT id,document_id,question FROM research_goals ORDER BY id DESC"):
        try:
            goals.require_goal(db, account, row["document_id"], row["id"])
        except sharing.AccessDenied:
            continue
        result.append(research_link(row))
    for row in agent_goals.scoped_rows(db, account):
        link = agent_link(db, account, row)
        if link:
            result.append(link)
    return result


def research_link(row):
    goal_id = row["id"]
    return {"id": goal_id, "kind": "research_goal", "label": row["question"],
            "url": f'/documents?document={row["document_id"]}&goal={goal_id}'}


def agent_link(db, account, row):
    try:
        goal = agent_goals.summary(db, account, row)
    except LookupError:
        return None
    if goal["source_unavailable"]:
        return None
    return {"id": goal["id"], "kind": "agent_goal", "label": goal["objective"],
            "url": f'/agent-goals?id={goal["id"]}'}


def link_for(db, account, kind, goal_id):
    if account is None or goal_id is None:
        return None
    if kind == "agent_goal":
        row = agent_goals.scoped_rows(db, account, goal_id=goal_id).fetchone()
        return agent_link(db, account, row) if row else None
    row = db.execute("SELECT document_id FROM research_goals WHERE id=?", (goal_id,)).fetchone()
    if row:
        try:
            return research_link(goals.require_goal(db, account, row["document_id"], goal_id))
        except sharing.AccessDenied:
            pass
    return None


def detail(db, account, document):
    context = db.execute(
        "SELECT topic,research_goal_id,agent_goal_id FROM document_contexts WHERE document_id=?", (document["id"],)
    ).fetchone()
    document.update(dict(context) if context else {"topic": ""})
    return redact(db, account, [document])[0]


def redact(db, account, items):
    links = {}
    for item in items:
        for kind in ("research_goal", "agent_goal"):
            field = kind + "_id"
            goal_id = item.pop(field, None)
            if goal_id is None:
                continue
            key = (kind, goal_id)
            if key not in links:
                links[key] = link_for(db, account, kind, goal_id)
            if links[key]:
                item[field] = goal_id
                item["goal_link"] = links[key]
    return items


def save(db, account, document_id, data):
    if not {"topic", "research_goal_id", "agent_goal_id"}.intersection(data):
        return
    existing = db.execute("SELECT * FROM document_contexts WHERE document_id=?", (document_id,)).fetchone()

    def value(name, default):
        return data.get(name, existing[name] if existing is not None else default)

    topic = value("topic", "")
    if not isinstance(topic, str) or len(topic.strip()) > 120:
        raise ValueError("Enter a topic of up to 120 characters or leave it blank.")
    goal_ids = []
    for kind in ("research_goal", "agent_goal"):
        field = kind + "_id"
        goal_id = value(field, None)
        if field in data and goal_id is not None:
            findings.positive_id(goal_id)
            if (existing is None or goal_id != existing[field]) and not link_for(db, account, kind, goal_id):
                raise sharing.AccessDenied
        goal_ids.append(goal_id)
    if all(goal_id is not None for goal_id in goal_ids):
        raise ValueError("Choose one linked goal.")
    if not topic.strip() and all(goal_id is None for goal_id in goal_ids):
        db.execute("DELETE FROM document_contexts WHERE document_id=?", (document_id,))
    else:
        db.execute("""
            INSERT INTO document_contexts(document_id,topic,research_goal_id,agent_goal_id) VALUES (?,?,?,?)
            ON CONFLICT(document_id) DO UPDATE SET topic=excluded.topic,
                research_goal_id=excluded.research_goal_id,agent_goal_id=excluded.agent_goal_id
        """, (document_id, topic.strip(), *goal_ids))
