"""Paper access, metadata, archive, and group HTTP operations."""

import re
from urllib.parse import parse_qs

from . import accounts, library, metadata_sync, metrics, sharing


def _positive_number(value, label):
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) >= 2**63:
        raise ValueError(f"Choose a valid {label}.")
    return int(value)


def read_papers(handler, db, url, account):
    if url.path == "/api/paper-archive":
        return library.paper_archive(db, account)
    if url.path == "/api/paper-comment-targets":
        return library.paper_comment_targets(db, account)
    params = parse_qs(url.query, keep_blank_values=True)

    def field(key, default=""):
        return params.get(key, [default])[0]

    if url.path in ("/api/paper-metrics", "/api/metric-history"):
        if account is None:
            raise accounts.SignInRequired
        if url.path == "/api/metric-history":
            before = field("before")
            return metrics.history(db, account, _positive_number(field("metric_id"), "metric"),
                                   _positive_number(before, "revision") if before else None)
        after = field("after", "0")
        removed = field("removed", "0")
        if removed not in ("0", "1"):
            raise ValueError("Use removed=0 or removed=1.")
        return metrics.list_metrics(db, account, _positive_number(field("paper_id"), "paper"),
                                    0 if after == "0" else _positive_number(after, "metric cursor"),
                                    removed=removed == "1")

    if url.path == "/api/paper-detail":
        return library.paper_detail(db, account, _positive_number(field("paper_id"), "paper"))

    query = field("q")
    publisher = field("publisher")
    if len(query) > 500 or len(publisher) > 4000:
        raise ValueError("Paper search or publisher is too long.")
    years = []
    for key in ("from_year", "through_year"):
        value = field(key)
        if value and not re.fullmatch(r"[1-9][0-9]{3}", value):
            raise ValueError("Enter a valid publication year range.")
        years.append(int(value) if value else None)
    from_year, through_year = years
    if from_year is not None and through_year is not None and from_year > through_year:
        raise ValueError("Enter a valid publication year range.")

    group = field("group")
    facets = field("facets") == "1"
    result = library.paper_catalog(
        db, account, query=query, group=_positive_number(group, "group") if group else None,
        publisher=publisher, from_year=from_year, through_year=through_year,
        page=_positive_number(field("page", "1"), "page"), facets=facets,
    )
    if facets:
        result["google_available"] = handler.google_available()
    return result


def update_paper(handler, db, data):
    if handler.path in ("/api/paper-metrics", "/api/metric-editors", "/api/claim-paper"):
        account = handler.require_account(db)
        if handler.path == "/api/paper-metrics":
            return metrics.correct(db, account, data)
        if handler.path == "/api/metric-editors":
            return metrics.set_editor(db, account, data)
        return metrics.claim_paper(db, account, data.get("paper_id"))

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
