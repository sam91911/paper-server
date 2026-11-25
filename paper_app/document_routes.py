"""Document HTTP operations."""

from . import sharing


def save(handler, db, data):
    kind = "discussion" if handler.path == "/api/discussions" else "document"
    document_id = sharing.save_document(db, handler.require_account(db), data, kind=kind)
    revision = db.execute("SELECT revision FROM documents WHERE id=?", (document_id,)).fetchone()["revision"]
    return {"document_id": document_id, "revision": revision}
