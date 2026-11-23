"""Extract metric candidates and store imported PDFs."""

import hashlib
import os
import re
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

from . import database as storage
from . import integrity, library, metrics, sharing

NUMBER = r"[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+−-]?\d+)?"
UNIT_GROUPS = {
    "energy efficiency": r"[TGMP]OPS\s*(?:/|per\s+)\s*W",
    "area efficiency": r"[TGMP]OPS\s*(?:/|per\s+)\s*mm(?:²|\^?2)",
    "throughput": r"[TGMP]OPS|(?:frames|images|tokens|samples|inferences)\s*/\s*s|FPS",
    "power": r"[mµμun]?W",
    "energy": r"[fnpµμum]?J(?:\s*/\s*(?:inference|op|MAC|bit))?",
    "latency": r"(?:ms|[µμun]s|seconds?)",
    "area": r"(?:mm|[µμu]m)(?:²|\^?2)",
    "frequency": r"[kMG]?Hz",
    "bandwidth": r"[kMGT]B\s*/\s*s|[kMGT]bps",
    "percentage": "%",
}
UNIT_LOOKUP = {f"u{index}": metric for index, metric in enumerate(UNIT_GROUPS)}
UNITS = "|".join(
    f"(?P<{group}>{pattern})"
    for group, pattern in zip(UNIT_LOOKUP, UNIT_GROUPS.values())
)


def measurement_pattern(units):
    return re.compile(
        rf"(?<![\w.,])(?P<first>{NUMBER})"
        rf"(?:\s*(?:[–—-]|\bto\b)\s*(?P<second>{NUMBER}))?\s*"
        rf"(?:{units})(?![\w/])",
        re.IGNORECASE,
    )


MEASUREMENT = measurement_pattern(UNITS)
KEYWORD_MEASUREMENT = measurement_pattern(
    UNITS + r"|(?P<keyword_unit>dBm?|[mµμ]?[VA]|[kMGT]i?B|[kMG]bps|°[CF])"
)
PERCENT_LABEL = re.compile(
    r"\b(?:top[- ]?[15](?:[- ]accuracy)?|accuracy|precision|recall|"
    r"f1(?: score)?|utilization|error rate)\b", re.IGNORECASE,
)
CONDITION = re.compile(
    r"\b(?:INT\s*\d+|FP\s*\d+|BF\s*\d+|\d+\s*[- ]?bit|"
    r"batch size\s*[:=]?\s*\d+|peak|average|mean|measured|simulated)\b",
    re.IGNORECASE,
)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def spreadsheet_text(value):
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def detection_keywords(values):
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError("Enter up to 20 detection keywords.")
    phrases = {}
    for value in values:
        if not isinstance(value, str) or len(value) > 60 or any(ord(char) < 32 for char in value):
            raise ValueError("Use keyword phrases of up to 60 characters.")
        phrase = " ".join(value.split())
        if phrase:
            phrases.setdefault(phrase.casefold(), phrase)
    return tuple(phrases.values())


def keyword_pattern(keywords):
    alternatives = "|".join(re.escape(word) for word in sorted(keywords, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE) if alternatives else None


def candidates(page, keyword=None):
    text = " ".join(page.split())
    measurements = KEYWORD_MEASUREMENT if keyword else MEASUREMENT
    for sentence in SENTENCE_BREAK.split(text):
        for match in measurements.finditer(sentence):
            group = match.lastgroup
            metric = UNIT_LOOKUP.get(group)
            # Limit evidence and qualifiers to nearby text, including on pages
            # where columns or table cells lack sentence punctuation.
            start = max(0, match.start() - 90)
            nearby = sentence[start:match.end() + 90]
            label = None
            if keyword:
                center = (match.start() + match.end()) / 2 - start
                label = min(keyword.finditer(nearby), key=lambda item: abs(center - item.start()), default=None)
                if label is None:
                    continue
            nearby = nearby.strip()
            if metric == "percentage":
                percentage = PERCENT_LABEL.search(nearby) or label
                if not percentage:
                    continue
                metric = percentage.group().lower()
            elif group == "keyword_unit":
                metric = label.group().lower()
            unit = re.sub(r"\s+", "", match[group].replace("μ", "µ"))
            if metric in ("energy efficiency", "area efficiency"):
                unit = re.sub("per", "/", unit, flags=re.IGNORECASE)
            conditions = list(dict.fromkeys(item.group() for item in CONDITION.finditer(nearby)))
            values = [(match["first"], "")]
            if match["second"] is not None:
                values = [(match["first"], "range start"), (match["second"], "range end")]
            for value, endpoint in values:
                number = Decimal(value.replace(",", "").replace("−", "-"))
                qualifiers = ", ".join(conditions + ([endpoint] if endpoint else []))
                yield metric, str(number), unit, qualifiers, nearby


def extract_pdf(payload, *, keywords=()):
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
        input=payload, capture_output=True, timeout=60, check=True,
    )
    pages = result.stdout.decode("utf-8").split("\f")
    keyword = keyword_pattern(keywords)
    rows = dict.fromkeys(
        (page_number, *row)
        for page_number, page in enumerate(pages, start=1)
        for row in candidates(page, keyword)
    )
    return rows, any(page.strip() for page in pages)


def detect_existing(database, paper_id, keywords, *, get_account, size_limit):
    def authorized_paper(db):
        account = get_account(db)
        paper = metrics.paper_for(db, account, paper_id)
        if not metrics.can_edit_all(paper, account):
            raise sharing.AccessDenied
        return paper

    with library.connect(database) as db:
        storage.begin(db)
        paper = authorized_paper(db)
    if not paper["sha256"]:
        raise ValueError("Attach a verified PDF before detecting metrics.")
    with Path(paper["path"]).open("rb") as stream:
        payload = stream.read(size_limit + 1)
    if len(payload) > size_limit:
        raise ValueError("Choose a PDF of up to 50 MiB.")
    if hashlib.sha256(payload).hexdigest() != paper["sha256"] or b"%PDF-" not in payload[:1024]:
        raise sharing.EditConflict("The local file no longer matches this paper record.")
    rows, has_text = extract_pdf(payload, keywords=keywords)
    with library.connect(database) as db:
        storage.begin(db, write=True)
        current = authorized_paper(db)
        if current["sha256"] != paper["sha256"]:
            raise sharing.EditConflict("The paper changed during detection. Try again.")
        rows = metrics.retain_detections(db, paper_id, rows)
        library.store(db, current["path"], rows, current["sha256"])
    return {"metrics": len(rows), "has_text": has_text}


def import_pdf(database, filename, payload, account, audience, recipients=None, *, keywords=()):
    digest = hashlib.sha256(payload).hexdigest()
    target = storage.pdf_directory(database) / digest / filename
    existed = target.exists()
    try:
        return _import_pdf(database, filename, payload, digest, account, audience, recipients, keywords)
    except Exception:
        # Serialize cleanup against other imports. Never remove a file another
        # successful transaction has already recorded, or one that predated us.
        if not existed and target.exists():
            with library.connect(database) as db:
                storage.begin(db, write=True)
                if not db.execute("SELECT 1 FROM papers WHERE path=?", (str(target),)).fetchone():
                    target.unlink(missing_ok=True)
        raise


def _import_pdf(database, filename, payload, digest, account, audience, recipients, keywords):
    rows, has_text = extract_pdf(payload, keywords=keywords)
    with library.connect(database) as db:
        storage.begin(db, write=True)
        existing = db.execute("SELECT id, path FROM papers WHERE sha256=?", (digest,)).fetchone()
        keeps_access = existing is not None
        source_id = existing["id"] if existing else None
        if existing:
            sharing.paper_for(db, existing["id"], account, owner_only=True)
        else:
            # Match a CSV-only record if its original PDF is still available.
            for old in db.execute(
                "SELECT p.id,p.path,a.owner_id FROM papers p LEFT JOIN paper_access a ON a.paper_id=p.id "
                "WHERE p.sha256 IS NULL"
            ).fetchall():
                source = Path(old["path"])
                if source.name != filename:
                    continue
                try:
                    matches = integrity.file_sha256(source) == digest
                except OSError:
                    continue
                if matches:
                    if old["owner_id"] is not None:
                        sharing.paper_for(db, old["id"], account, owner_only=True)
                        keeps_access = True
                    source_id = library.store(db, source, (), digest)
                    break

        if not keeps_access:
            sharing.recipient_ids(db, recipients)
        directory = storage.pdf_directory(database) / digest
        directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.mkdir(mode=0o700, exist_ok=True)
        target = Path(existing["path"]) if existing else directory / filename
        if target.parent != directory:
            target = directory / filename
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temp:
            temporary = Path(temp.name)
            try:
                temp.write(payload)
                temp.close()
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        rows = metrics.retain_detections(db, source_id, rows)
        paper_id = library.store(db, target, rows, digest)
        db.execute("UPDATE papers SET path=? WHERE id=?", (str(target), paper_id))
        db.execute("UPDATE paper_metadata_checks SET next_check=0,detected_doi=NULL WHERE paper_id=?", (paper_id,))
        if not keeps_access:
            db.execute("INSERT INTO paper_access VALUES (?,?,?)", (paper_id, account["id"], audience))
            sharing.set_recipients(db, "paper", paper_id, recipients)
    return {"paper_id": paper_id, "metrics": len(rows), "has_text": has_text}
