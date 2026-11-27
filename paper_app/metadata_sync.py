"""Fill missing bibliographic fields without sending PDF contents to Crossref."""

import hashlib
import logging
import re
import subprocess
import time
from pathlib import Path

from . import database as storage
from . import crossref, library

LOG = logging.getLogger(__name__)
FIELDS = library.METADATA[:-1]
RETRY_SECONDS = 7 * 24 * 60 * 60
ERROR_SECONDS = 60 * 60
FIRST_PAGE_LIMIT = 50 * 1024 * 1024
POLL_SECONDS = 30
MAX_IDLE_SECONDS = 120
BATCH_SIZE = 16
MISSING_FIELDS = " OR ".join(f"trim({field})=''" for field in FIELDS)
SOURCE_AVAILABLE = "(sha256 IS NOT NULL OR trim(doi)<>'')"


def initialize(db):
    db.execute("CREATE INDEX IF NOT EXISTS paper_metadata_due ON paper_metadata_checks(next_check,paper_id)")
    db.execute(f"CREATE INDEX IF NOT EXISTS paper_metadata_unchecked ON papers(id) "
               f"WHERE {SOURCE_AVAILABLE} AND ({MISSING_FIELDS})")


def set_title_lookup(db, paper_id, allow):
    db.execute(
        "INSERT INTO paper_metadata_checks(paper_id,allow_title) VALUES (?,?) "
        "ON CONFLICT(paper_id) DO UPDATE SET allow_title=excluded.allow_title,next_check=0",
        (paper_id, int(allow)),
    )


def pending(db, now):
    # Bound each ordered candidate stream before joining wide paper rows.
    return db.execute(
        f"""WITH unchecked AS (
            SELECT p.id,0 AS due FROM papers p
            WHERE {SOURCE_AVAILABLE} AND ({MISSING_FIELDS}) AND NOT EXISTS (
                SELECT 1 FROM paper_metadata_checks c WHERE c.paper_id=p.id
            ) AND NOT EXISTS (SELECT 1 FROM archived_papers a WHERE a.paper_id=p.id)
            ORDER BY p.id LIMIT {BATCH_SIZE}
        ), scheduled AS (
            SELECT c.paper_id AS id,c.next_check AS due
            FROM paper_metadata_checks c JOIN papers p ON p.id=c.paper_id
            WHERE c.next_check<=? AND ({MISSING_FIELDS}) AND (
               trim(p.doi)<>'' OR c.allow_title=1 OR c.detected_doi<>'' OR
               (c.detected_doi IS NULL AND p.sha256 IS NOT NULL)
            ) AND NOT EXISTS (SELECT 1 FROM archived_papers a WHERE a.paper_id=p.id)
            ORDER BY c.next_check,c.paper_id LIMIT {BATCH_SIZE}
        ), candidates AS (
            SELECT id,due FROM unchecked UNION ALL SELECT id,due FROM scheduled
            ORDER BY due,id LIMIT {BATCH_SIZE}
        )
        SELECT p.*,COALESCE(c.allow_title,0) AS allow_title,c.detected_doi
        FROM candidates k JOIN papers p ON p.id=k.id
        LEFT JOIN paper_metadata_checks c ON c.paper_id=p.id ORDER BY k.due,p.id""", (now,),
    ).fetchall()


def detect_doi(paper):
    if not paper["sha256"]:
        return ""
    try:
        with Path(paper["path"]).open("rb") as stream:
            payload = stream.read(FIRST_PAGE_LIMIT + 1)
        if len(payload) > FIRST_PAGE_LIMIT or hashlib.sha256(payload).hexdigest() != paper["sha256"]:
            return ""
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "1", "-enc", "UTF-8", "-", "-"],
            input=payload, capture_output=True, check=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.decode("utf-8", errors="replace")
    text = re.split(r"^\s*references\s*$", text, maxsplit=1, flags=re.I | re.M)[0]
    dois = {match.rstrip(".,;").lower() for match in re.findall(
        r"(?:\bdoi\s*:\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s<>]+)", text, re.I,
    )}
    return next(iter(dois)) if len(dois) == 1 else ""


def title_key(title):
    return tuple(re.findall(r"\w+", title.casefold()))


def match_paper(paper, detected_doi):
    doi = paper["doi"].strip() or detected_doi
    if doi:
        try:
            matches = crossref.lookup("doi", doi)
        except ValueError:
            matches = []
        if matches:
            match = matches[0]
            if paper["doi"].strip() or not paper["title"].strip() or (
                title_key(paper["title"]) == title_key(match["title"])
            ):
                return match
    if not paper["allow_title"]:
        return None
    title = paper["title"].strip() or Path(paper["path"]).stem.replace("_", " ").strip()
    if not title or len(title) > 500:
        return None
    exact = [match for match in crossref.lookup("title", title)
             if match["doi"] and title_key(match["title"]) == title_key(title)
             and (not paper["doi"].strip() or match["doi"].lower() == paper["doi"].strip().lower())]
    return exact[0] if len(exact) == 1 else None


def current_paper(db, paper_id):
    return db.execute(
        "SELECT p.*,COALESCE(c.allow_title,0) AS allow_title,c.detected_doi "
        "FROM papers p LEFT JOIN paper_metadata_checks c ON c.paper_id=p.id WHERE p.id=? "
        "AND NOT EXISTS (SELECT 1 FROM archived_papers a WHERE a.paper_id=p.id)",
        (paper_id,),
    ).fetchone()


def check_paper(database, paper):
    with library.connect(database) as db:
        current = current_paper(db, paper["id"])
    if current is None or dict(current) != dict(paper):
        return
    detected = paper["detected_doi"]
    if detected is None and not paper["doi"].strip():
        detected = detect_doi(paper)
    delay = ERROR_SECONDS if detected is None and not paper["doi"].strip() else RETRY_SECONDS
    try:
        match = match_paper(paper, detected)
    except (ValueError, RuntimeError):
        match = None
        delay = ERROR_SECONDS
    with library.connect(database) as db:
        storage.begin(db, write=True)
        current = current_paper(db, paper["id"])
        if current is None or dict(current) != dict(paper):
            return
        if match:
            data = {field: paper[field] if paper[field].strip()
                    else str(match.get(field) or "")[:4000] for field in FIELDS}
            if any(data[field] != paper[field] for field in FIELDS):
                data["source"] = paper["source"] or "Crossref (automatic)"
                library.save_metadata(db, paper["id"], data)
        db.execute(
            "INSERT INTO paper_metadata_checks(paper_id,next_check,detected_doi) VALUES (?,?,?) "
            "ON CONFLICT(paper_id) DO UPDATE SET next_check=excluded.next_check,detected_doi=excluded.detected_doi",
            (paper["id"], int(time.time()) + delay, detected),
        )


def run(database, stop):
    delay = POLL_SECONDS
    while not stop.is_set():
        papers = []
        try:
            with library.connect(database) as db:
                papers = pending(db, int(time.time()))
            if papers:
                delay = POLL_SECONDS
            for paper in papers:
                if stop.is_set():
                    return
                check_paper(database, paper)
                stop.wait(1)
        except storage.ERRORS:
            LOG.exception("Could not check missing paper metadata")
        if stop.wait(delay):
            return
        if not papers:
            delay = min(delay * 2, MAX_IDLE_SECONDS)
