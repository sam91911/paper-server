"""Paper access, metadata, archive, and group HTTP operations."""

from . import library, metadata_sync, sharing


def update_paper(handler, db, data):
    paper_id = data.get("paper_id")
    if type(paper_id) is not int:
        raise ValueError("Select a paper")
    if handler.path == "/api/paper-access":
        sharing.set_paper_audience(db, paper_id, handler.require_account(db), data.get("audience"),
                                   data.get("recipients"))
        if "allow_title" in data:
            if type(data["allow_title"]) is not bool:
                raise ValueError("Choose whether to allow a title lookup.")
            metadata_sync.set_title_lookup(db, paper_id, data["allow_title"])
        return
    account = handler.current_account(db)
    sharing.paper_for(db, paper_id, account, owner_only=handler.path in (
        "/api/metadata", "/api/archive-paper", "/api/memberships",
    ))
    if handler.path == "/api/metadata":
        library.save_metadata(db, paper_id, data)
        db.execute("UPDATE paper_metadata_checks SET next_check=0 WHERE paper_id=?", (paper_id,))
    elif handler.path == "/api/archive-paper":
        archived = data.get("archived")
        if type(archived) is not bool:
            raise ValueError("Choose whether to archive or restore the paper")
        library.set_archived(db, paper_id, archived)
    else:
        handler.require_human(db)
        library.set_memberships(db, paper_id, data.get("groups"))
