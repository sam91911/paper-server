"""Per-item tags with normalized matching and display labels."""

import unicodedata

TABLES = {"paper": ("paper_tags", "paper_id"), "document": ("document_tags", "document_id")}
SCHEMA = tuple(f"""CREATE TABLE IF NOT EXISTS {table} (
    {field} INTEGER NOT NULL REFERENCES {kind}s(id) ON DELETE CASCADE,
    tag TEXT NOT NULL, label TEXT NOT NULL, PRIMARY KEY({field},tag)
)""" for kind, (table, field) in TABLES.items()) + (
    "CREATE INDEX IF NOT EXISTS paper_tags_filter ON paper_tags(tag,paper_id)",
    "CREATE INDEX IF NOT EXISTS document_tags_filter ON document_tags(tag,document_id)",
)


def label(value):
    if not isinstance(value, str) or any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("Use plain-text tags of up to 50 characters.")
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    if not value or len(value) > 50 or "," in value:
        raise ValueError("Use comma-free tags of up to 50 characters.")
    return value


def key(value):
    return label(value).casefold()


def save(db, kind, item_id, values):
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError("Use up to 20 tags.")
    labels = {}
    for value in values:
        text = label(value)
        labels.setdefault(text.casefold(), text)
    table, field = TABLES[kind]
    db.execute(f"DELETE FROM {table} WHERE {field}=?", (item_id,))
    db.executemany(f"INSERT INTO {table}({field},tag,label) VALUES (?,?,?)",
                   ((item_id, tag, text) for tag, text in labels.items()))


def attach(db, kind, items):
    table, field = TABLES[kind]
    by_id = {item["id"]: [] for item in items}
    ids = list(by_id)
    for start in range(0, len(ids), 200):
        batch = ids[start:start + 200]
        placeholders = ",".join("?" for _ in batch)
        for item_id, text in db.execute(f"SELECT {field},label FROM {table} WHERE {field} IN ({placeholders}) ORDER BY tag",
                                        batch):
            by_id[item_id].append(text)
    for item in items:
        item["tags"] = by_id[item["id"]]
    return items
