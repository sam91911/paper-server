"""Extract metric candidates and store imported PDFs."""

import hashlib
import os
import re
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

from . import database as storage
from . import library, sharing

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
MEASUREMENT = re.compile(
    rf"(?<![\w.,])(?P<first>{NUMBER})"
    rf"(?:\s*(?:[–—-]|\bto\b)\s*(?P<second>{NUMBER}))?\s*"
    rf"(?:{UNITS})(?![\w/])",
    re.IGNORECASE,
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


def candidates(page):
    text = " ".join(page.split())
    for sentence in SENTENCE_BREAK.split(text):
        for match in MEASUREMENT.finditer(sentence):
            group = next(group for group in UNIT_LOOKUP if match[group] is not None)
            metric = UNIT_LOOKUP[group]
            # Limit evidence and qualifiers to nearby text, including on pages
            # where columns or table cells lack sentence punctuation.
            nearby = sentence[max(0, match.start() - 90):match.end() + 90].strip()
            if metric == "percentage":
                label = PERCENT_LABEL.search(nearby)
                if not label:
                    continue
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


def extract_pdf(payload):
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
        input=payload, capture_output=True, timeout=60, check=True,
    )
    pages = result.stdout.decode("utf-8").split("\f")
    rows = dict.fromkeys(
        (page_number, *row)
        for page_number, page in enumerate(pages, start=1)
        for row in candidates(page)
    )
    return rows, any(page.strip() for page in pages)


def import_pdf(database, filename, payload, account, audience, recipients=None):
    digest = hashlib.sha256(payload).hexdigest()
    target = storage.pdf_directory(database) / digest / filename
    existed = target.exists()
    try:
        return _import_pdf(database, filename, payload, account, audience, recipients)
    except Exception:
        # Serialize cleanup against other imports. Never remove a file another
        # successful transaction has already recorded, or one that predated us.
        if not existed and target.exists():
            with library.connect(database) as db:
                storage.begin(db, write=True)
                if not db.execute("SELECT 1 FROM papers WHERE path=?", (str(target),)).fetchone():
                    target.unlink(missing_ok=True)
        raise


def _import_pdf(database, filename, payload, account, audience, recipients=None):
    digest = hashlib.sha256(payload).hexdigest()
    rows, has_text = extract_pdf(payload)
    with library.connect(database) as db:
        storage.begin(db, write=True)
        existing = db.execute("SELECT id, path FROM papers WHERE sha256=?", (digest,)).fetchone()
        if existing:
            sharing.paper_for(db, existing["id"], account, owner_only=True)
        else:
            # Match a CSV-only record if its original PDF is still available.
            for old in db.execute("SELECT path FROM papers WHERE sha256 IS NULL").fetchall():
                source = Path(old["path"])
                if source.name != filename:
                    continue
                try:
                    with source.open("rb") as stream:
                        matches = hashlib.file_digest(stream, "sha256").hexdigest() == digest
                except OSError:
                    continue
                if matches:
                    library.store(db, source, (), digest)
                    break

        if not existing:
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
        paper_id = library.store(db, target, rows, digest)
        db.execute("UPDATE papers SET path=? WHERE id=?", (str(target), paper_id))
        db.execute("UPDATE paper_metadata_checks SET next_check=0,detected_doi=NULL WHERE paper_id=?", (paper_id,))
        if not existing:
            db.execute("INSERT INTO paper_access VALUES (?,?,?)", (paper_id, account["id"], audience))
            sharing.set_recipients(db, "paper", paper_id, recipients)
    return {"paper_id": paper_id, "metrics": len(rows), "has_text": has_text}
