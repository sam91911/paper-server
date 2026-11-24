"""HTTP operations for paper and document discussions."""

from . import library, sharing


def update_comment(handler, db, data):
    account = handler.require_account(db)
    paper_id, document_id = data.get("paper_id"), data.get("document_id")
    if type(paper_id) is int and document_id is None:
        sharing.paper_for(db, paper_id, account)
    elif type(document_id) is int and paper_id is None:
        if sharing.document_for(db, account, document_id) is None:
            raise sharing.AccessDenied
    else:
        raise ValueError("Select a paper or document.")
    comment_id = data.get("comment_id")
    if comment_id is not None and type(comment_id) is not int:
        raise ValueError("Select a comment")
    if handler.path == "/api/delete-comment":
        if comment_id is None:
            raise ValueError("Select a comment")
        library.delete_comment(db, paper_id, comment_id, account, document_id)
        return
    comment_id = library.save_comment(
        db, paper_id, data.get("body"), account, comment_id, kind=data.get("kind", "user"),
        parent_id=data.get("parent_id"), doi_refs=data.get("doi_refs"),
        audience=data.get("audience"), location=data.get("location"),
        recipients=data.get("recipients"), document_id=document_id, finding_id=data.get("finding_id"),
        goal_id=data.get("goal_id"),
    )
    return {"comment_id": comment_id}
