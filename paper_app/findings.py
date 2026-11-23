"""Research findings and citations scoped to a Markdown workspace."""

import hashlib
import json
import os
import re
import subprocess
from decimal import Decimal, localcontext
from pathlib import Path

from . import experiments, sharing

SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS research_findings (
    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
    author_id INTEGER NOT NULL REFERENCES accounts(id), author_role TEXT NOT NULL, statement TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('observation','baseline','run_result')),
    metric TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL, conditions TEXT NOT NULL,
    evidence TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
)
""",
    "CREATE INDEX IF NOT EXISTS findings_document ON research_findings(document_id,id)",
)
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")


def positive_id(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("Choose a valid ID or position.")
    return value


def require_document(db, account, document_id):
    document = sharing.document_for(db, account, positive_id(document_id))
    if document is None:
        raise sharing.AccessDenied
    return document


def _pdf_page_count(paper):
    try:
        with Path(paper["path"]).open("rb") as stream:
            payload = stream.read(50 * 1024 * 1024 + 1)
        if len(payload) > 50 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != paper["sha256"]:
            raise ValueError("Re-import the verified PDF before citing it.")
        result = subprocess.run(["pdfinfo", "-"], input=payload, capture_output=True,
                                check=True, timeout=15, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Could not verify the PDF page with Poppler's pdfinfo.") from None
    count = re.search(rb"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)
    if not count:
        raise ValueError("Could not read the PDF page count.")
    return int(count[1])


def _reference(db, account, ref, *, pdf_pages=None):
    if not isinstance(ref, dict):
        raise ValueError("Choose a PDF page, document lines, or a run artifact version.")
    kind, target_id = ref.get("kind"), positive_id(ref.get("id"))
    citation = {"kind": kind, "id": target_id}
    writing = pdf_pages is not None
    if kind == "pdf":
        paper = sharing.paper_for(db, target_id, account)
        if not paper["sha256"] or (not writing and paper["sha256"] != ref["sha256"]):
            raise sharing.AccessDenied
        page = positive_id(ref.get("page"))
        if writing:
            if target_id not in pdf_pages:
                pdf_pages[target_id] = _pdf_page_count(paper)
            if page > pdf_pages[target_id]:
                raise ValueError("This PDF has no such page.")
        citation.update(page=page, sha256=paper["sha256"])
        details = {"title": paper["title"] or f"Paper #{target_id}",
                   "url": f"/papers/{target_id}/source.pdf#page={page}"}
    elif kind == "document":
        doc = require_document(db, account, target_id)
        start = positive_id(ref.get("start"))
        end = positive_id(ref.get("end", start))
        revision = positive_id(ref.get("revision"))
        stale = revision != doc["revision"]
        if writing and stale:
            raise sharing.EditConflict("The cited document changed. Check the lines in its current revision.")
        if writing and (end < start or end > doc["markdown"].count("\n") + 1):
            raise ValueError("Choose a line range within the cited document.")
        citation.update(start=start, end=end, revision=revision)
        details = {"title": doc["title"], "stale": stale,
                   "url": f"/documents?document={target_id}"}
        if not stale:
            details["url"] += f"&line={start}&end={end}&revision={revision}"
    elif kind == "run_artifact":
        version = db.execute("SELECT id,item_id,number,sha256 FROM research_versions WHERE id=?",
                             (target_id,)).fetchone()
        if not version or not version["sha256"] or (not writing and version["sha256"] != ref["sha256"]):
            raise sharing.AccessDenied
        item = experiments.require_item(db, version["item_id"], account)
        if item["run_id"] is None:
            raise ValueError("Choose an uploaded artifact that belongs to a run.")
        citation["sha256"] = version["sha256"]
        details = {"title": item["title"], "version": version["number"], "run_id": item["run_id"],
                   "experiment_id": item["experiment_id"], "url": f"/research-versions/{target_id}/file"}
    else:
        raise ValueError("Choose a PDF page, document lines, or a run artifact version.")
    return citation if writing else {**citation, **details}


def _rows(db, document_id, discussions_only):
    return db.execute(
        "SELECT f.*, COALESCE(NULLIF(a.display_name,''),a.username) AS author_name "
        "FROM research_findings f JOIN accounts a ON a.id=f.author_id "
        "WHERE (:document IS NULL OR f.document_id=:document) "
        "AND (:discussions=0 OR EXISTS (SELECT 1 FROM comments c WHERE c.finding_id=f.id)) ORDER BY f.id DESC",
        {"document": document_id, "discussions": discussions_only},
    )


def visible(db, account, document_id=None, *, discussions_only=False):
    if not account:
        return
    if document_id is None:
        documents = {doc["id"] for doc in sharing.documents_for(db, account, targets_only=True)}
    else:
        documents = {document_id} if sharing.document_for(db, account, document_id) else set()
    if not documents:
        return
    for row in _rows(db, document_id, discussions_only):
        if row["document_id"] not in documents:
            continue
        try:
            evidence = [_reference(db, account, ref) for ref in json.loads(row["evidence"])]
        except sharing.AccessDenied:
            continue
        yield dict(row, evidence=evidence)


def require_finding(db, account, document_id, finding_id):
    require_document(db, account, document_id)
    row = db.execute("SELECT * FROM research_findings WHERE id=? AND document_id=?",
                     (positive_id(finding_id), document_id)).fetchone()
    if not row:
        raise sharing.AccessDenied
    evidence = [_reference(db, account, ref) for ref in json.loads(row["evidence"])]
    return dict(row, evidence=evidence)


def save(db, account, data):
    document_id = require_document(db, account, data.get("document_id"))["id"]
    statement = experiments.validate_text(data.get("statement"), "a finding", 20000, required=True)
    kind = data.get("kind", "observation")
    if kind not in ("observation", "baseline", "run_result"):
        raise ValueError("Choose a finding type.")
    refs = data.get("evidence")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
        raise ValueError("Add between 1 and 20 evidence references.")
    finding_id = data.get("id")
    old = None
    if finding_id is not None:
        old = require_finding(db, account, document_id, finding_id)
        if old["author_id"] != account["id"]:
            raise sharing.AccessDenied
        if data.get("revision") != old["revision"]:
            raise sharing.EditConflict("This finding changed. Reload it before saving.")
    pdf_pages = {}
    evidence = [_reference(db, account, ref, pdf_pages=pdf_pages) for ref in refs]
    kinds = {ref["kind"] for ref in evidence}
    if kind == "baseline" and ("pdf" not in kinds or data.get("verified_baseline") is not True):
        raise ValueError("Verify the published baseline against a cited PDF page.")
    if kind == "run_result" and "run_artifact" not in kinds:
        raise ValueError("Cite an uploaded run artifact for a run result.")
    metric = experiments.validate_text(data.get("metric", ""), "a metric", 160).strip()
    unit = experiments.validate_text(data.get("unit", ""), "a unit", 80).strip()
    conditions = experiments.validate_text(data.get("conditions", ""), "measurement conditions", 2000).strip()
    value = data.get("value", "")
    if value != "" or metric or unit or conditions:
        if not (metric and unit and conditions and isinstance(value, str)
                and len(value) <= 40 and NUMBER.fullmatch(value)):
            raise ValueError("Enter a metric, decimal value, unit, and measurement conditions together.")
    values = (statement, kind, metric, value, unit, conditions, json.dumps(evidence))
    if old is None:
        finding_id = db.execute(
            "INSERT INTO research_findings(document_id,author_id,author_role,statement,kind,metric,value,unit,conditions,evidence)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", (document_id, account["id"], account["role"], *values),
        ).lastrowid
        return {"id": finding_id, "revision": 1}
    in_use = db.execute("""
        SELECT EXISTS (SELECT 1 FROM comments WHERE finding_id=:id)
            OR EXISTS (SELECT 1 FROM research_goal_evidence WHERE finding_id=:id)
            OR EXISTS (SELECT 1 FROM research_goal_briefs WHERE baseline_id=:id)
            OR EXISTS (SELECT 1 FROM research_goal_decisions WHERE result_id=:id)
    """, {"id": finding_id}).fetchone()[0]
    if in_use:
        old_targets = {(ref["kind"], ref["id"]) for ref in old["evidence"]}
        new_targets = {(ref["kind"], ref["id"]) for ref in evidence}
        if old_targets != new_targets:
            raise ValueError("A finding linked to a discussion or goal must keep its evidence targets. Add a follow-up finding to cite different sources.")
    db.execute("UPDATE research_findings SET statement=?,kind=?,metric=?,value=?,unit=?,conditions=?,"
               "evidence=?,revision=revision+1 WHERE id=?", (*values, finding_id))
    return {"id": finding_id, "revision": old["revision"] + 1}


def compare(left, right):
    reasons = []
    if not left["value"] or not right["value"]:
        reasons.append("A finding is qualitative.")
    if any(ref.get("stale") for finding in (left, right) for ref in finding["evidence"]):
        reasons.append("A cited document revision has changed.")
    for field, label in (("metric", "Metrics"), ("unit", "Units"), ("conditions", "Measurement conditions")):
        if left["value"] and right["value"] and left[field] != right[field]:
            reasons.append(f"{label} differ.")
    difference = None
    if not reasons:
        with localcontext() as context:
            context.prec = 82
            difference = format(abs(Decimal(right["value"]) - Decimal(left["value"])), "f")
    return {"difference": difference, "reasons": reasons}


def query_id(params, name):
    values = params.get(name, [])
    if len(values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,18}", values[0]):
        raise ValueError("Choose a valid document or finding ID.")
    return positive_id(int(values[0]))


def read(db, account, params):
    document_id = query_id(params, "document_id")
    require_document(db, account, document_id)
    if "left" in params or "right" in params:
        pair = [query_id(params, name) for name in ("left", "right")]
        if pair[0] == pair[1]:
            raise ValueError("Choose two different findings.")
        selected = [require_finding(db, account, document_id, finding_id) for finding_id in pair]
        return {"comparison": {**compare(*selected), "findings": [
            {key: finding[key] for key in ("id", "value", "unit")} for finding in selected
        ]}}
    return {"findings": list(visible(db, account, document_id)),
            "experiments": [{"id": row["id"], "title": row["title"]}
                            for row in experiments.visible_experiments(db, account, document_id)]}
