"""HTTP operations for paper and document discussions."""

from . import library, sharing


def update_comment(handler, db, data):
    account = handler.require_account(db)
    paper_id, document_id = data.get("paper_id"), data.get("document_id")
    document = None
    if type(paper_id) is int and document_id is None:
        sharing.paper_for(db, paper_id, account)
    elif type(document_id) is int and paper_id is None:
        document = sharing.document_for(db, account, document_id)
        if document is None:
            raise sharing.AccessDenied
    else:
        raise ValueError("Select a paper or document.")
    comment_id = data.get("comment_id")
    if comment_id is not None and type(comment_id) is not int:
        raise ValueError("Select a comment")
    if handler.path == "/api/thread-votes":
        kind, target_id = "comment", comment_id
        if comment_id is None:
            if document is None or document["kind"] != "discussion":
                raise ValueError("Choose a discussion or comment to vote on.")
            kind, target_id = "discussion", document_id
        elif not library.can_reply(db, paper_id, comment_id, account, document_id):
            raise sharing.AccessDenied
        vote = data.get("vote")
        if type(vote) is not int or vote not in (-1, 0, 1):
            raise ValueError("Choose an upvote, downvote, or clear your vote.")
        if vote:
            db.execute(
                "INSERT INTO thread_votes(kind,target_id,account_id,value) VALUES (?,?,?,?) "
                "ON CONFLICT(kind,target_id,account_id) DO UPDATE SET value=excluded.value",
                (kind, target_id, account["id"], vote),
            )
        else:
            db.execute("DELETE FROM thread_votes WHERE kind=? AND target_id=? AND account_id=?",
                       (kind, target_id, account["id"]))
        score = db.execute("SELECT COALESCE(SUM(value),0) FROM thread_votes WHERE kind=? AND target_id=?",
                           (kind, target_id)).fetchone()[0]
        return {"vote_score": int(score), "my_vote": vote}
    if handler.path == "/api/delete-comment":
        if comment_id is None:
            raise ValueError("Select a comment")
        library.delete_comment(db, paper_id, comment_id, account, document_id)
        return
    if document is not None and document["kind"] == "discussion" and any(
        data.get(field) for field in ("location", "doi_refs", "finding_id", "goal_id")
    ):
        raise ValueError("Use plain discussion comments in this workspace.")
    comment_id = library.save_comment(
        db, paper_id, data.get("body"), account, comment_id, kind=data.get("kind", "user"),
        parent_id=data.get("parent_id"), doi_refs=data.get("doi_refs"),
        audience=data.get("audience"), location=data.get("location"),
        recipients=data.get("recipients"), document_id=document_id, finding_id=data.get("finding_id"),
        goal_id=data.get("goal_id"),
        scheduled_at=data.get("scheduled_at", sharing.UNSET),
    )
    return {"comment_id": comment_id}
