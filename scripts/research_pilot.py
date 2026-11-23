"""Create a synthetic research library for the browser and API walkthrough."""

import argparse
import csv
import io
import secrets
from pathlib import Path

from paper_app import accounts, experiments, findings, goals, library, pdf, sharing

STANDARD = "Ten scans; exact document match"
CLEAN = "Five clean scans; exact document match"


def methods_pdf():
    stream = (
        b"BT /F1 16 Tf 54 730 Td (Synthetic document transcription methods) Tj "
        b"0 -26 Td (Baseline: 80% accuracy on ten scans by exact document match.) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, entry in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + entry + b"\nendobj\n")
    xref = len(output)
    count = len(objects) + 1
    output.extend(f"xref\n0 {count}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def run_transcription(count, *, correct_all):
    """Score synthetic external transcriptions and export the per-document results."""
    output = io.StringIO(newline="")
    rows = csv.writer(output)
    rows.writerow(("sample", "expected", "transcribed", "exact_match"))
    correct = 0
    for index in range(count):
        expected = f"ITEM-{index}-O"
        result = expected if correct_all or index < count - 1 else f"ITEM-{index}-0"
        match = expected == result
        correct += match
        rows.writerow((index + 1, expected, result, int(match)))
    return str(correct * 100 // count), output.getvalue().encode()


def record_external_run(db, actor, document_id, experiment_id, *, clean=False):
    title, count, conditions = ("Clean scans only", 5, CLEAN) if clean else ("Full benchmark", 10, STANDARD)
    run_id = experiments.save_run(db, actor, {
        "title": title, "experiment_id": experiment_id, "status": "complete", "audience": "local",
        "methods": "Compare the normalized transcription with the expected text for each scan.",
        "settings": conditions,
    })
    score, output = run_transcription(count, correct_all=clean)
    item_id = experiments.save_item(db, actor, {
        "experiment_id": experiment_id, "run_id": run_id, "kind": "data", "title": "Per-scan results",
        "filename": "transcriptions.csv", "audience": "local",
    }, output)
    version_id = db.execute("SELECT id FROM research_versions WHERE item_id=?", (item_id,)).fetchone()[0]
    ref = {"kind": "run_artifact", "id": version_id}
    result_id = findings.save(db, actor, {
        "document_id": document_id, "statement": f"{title} scored {score}% accuracy.", "kind": "run_result",
        "evidence": [ref], "metric": "Accuracy", "value": score, "unit": "%", "conditions": conditions,
    })["id"]
    return run_id, result_id, ref


def populate(database):
    if database.exists() or database.with_name(database.name + ".pdfs").exists():
        raise ValueError("Choose a new pilot database path.")
    library.initialize(database)
    password = secrets.token_urlsafe(18)
    human = {"id": 1, "username": "pilot-researcher", "role": "user"}
    agent = {"id": 2, "username": "pilot-agent", "role": "local"}
    with library.connect(database) as db:
        accounts.create_account(db, human["username"], password, human["role"])
        accounts.create_account(db, agent["username"], secrets.token_urlsafe(18), agent["role"])
        ai_key = accounts.create_key(db, agent["id"], "Synthetic research pilot")

    paper_id = pdf.import_pdf(database, "transcription-methods.pdf", methods_pdf(), human, "local")["paper_id"]
    with library.connect(database) as db:
        db.execute("UPDATE papers SET title=? WHERE id=?", ("Synthetic document transcription methods", paper_id))
        document_id = sharing.save_document(db, human, {
            "title": "Does preprocessing improve document transcription?",
            "markdown": "# Research question\nDoes preprocessing improve exact-match transcription?\n\n"
                        "Compare the full ten-scan benchmark against the published methods. "
                        "Record the clean-only run separately and inspect the remaining error.",
            "audience": "local",
        })
        experiment_id = experiments.save_experiment(db, human, {
            "title": "Synthetic document transcription", "research_document_id": document_id, "audience": "local",
        })
        paper_ref = {"kind": "pdf", "id": paper_id, "page": 1}

        def add_finding(author, statement, kind, evidence, **measurement):
            return findings.save(db, author, dict(document_id=document_id, statement=statement, kind=kind,
                                                  evidence=evidence, **measurement))["id"]

        baseline = add_finding(human, "The published baseline correctly transcribed eight of ten scans.",
                               "baseline", [paper_ref], verified_baseline=True, metric="Accuracy",
                               value="80", unit="%", conditions=STANDARD)
        run_refs, result_ids = [], []
        for clean in (False, True):
            _, result_id, ref = record_external_run(db, human, document_id, experiment_id, clean=clean)
            run_refs.append(ref)
            result_ids.append(result_id)
        observation = add_finding(agent, "The remaining error replaced the capital letter O with the digit 0.",
                                  "observation", run_refs[:1])
        conclusion = add_finding(
            human, "The comparable run scored higher than the published baseline. The clean-only run uses "
                   "a different sample, and the remaining O/0 error suggests a targeted follow-up.",
            "observation", [paper_ref, *run_refs],
        )
        library.save_comment(db, None, "Does preprocessing help on the hardest samples?", human,
                             document_id=document_id, finding_id=conclusion, audience="local")
    return {"human_username": human["username"], "human_password": password, "ai_key": ai_key,
            "document": document_id, "baseline": baseline, "full_run": result_ids[0],
            "clean_run": result_ids[1], "observation": observation, "conclusion": conclusion,
            "runs": run_refs, "paper": paper_id, "experiment": experiment_id}


def populate_goal_workflow(database, pilot):
    human = {"id": 1, "role": "user"}
    agent = {"id": 2, "role": "local"}
    document_id = pilot["document"]
    with library.connect(database) as db:
        def change(actor, action, **data):
            return goals.update(db, actor, dict(action=action, document_id=document_id, **data))

        goal = change(agent, "propose", question="Can preprocessing improve ten-scan accuracy?",
                      rationale="The published baseline leaves two errors to investigate.",
                      uncertainty="Does preprocessing help on the full benchmark?",
                      evidence_ids=[pilot["baseline"]])
        alternative = change(agent, "propose", question="Should we target O/0 confusions?",
                             rationale="The full run still confused an O with a zero.",
                             uncertainty="Does this error recur on a larger sample?",
                             evidence_ids=[pilot["observation"]])
        change(human, "rank", goal_id=alternative["id"], revision=alternative["revision"], priority=2, selected=False)
        rank = change(human, "rank", goal_id=goal["id"], revision=goal["revision"], priority=1, selected=True)
        brief = change(agent, "draft", goal_id=goal["id"], approach="Score normalized transcriptions.",
                       baseline_id=pilot["baseline"], criterion="Reach 90% accuracy on the ten-scan benchmark.",
                       conditions=STANDARD, budget="One local run using the ten synthetic scans.")
        confirmed = change(human, "confirm", goal_id=goal["id"], brief_id=brief["brief_id"], revision=rank["revision"])
        library.save_comment(db, None, "Use all ten scans for the feasibility decision.", human,
                             document_id=document_id, goal_id=goal["id"], audience="local")
        revision = confirmed["revision"]
        for clean, outcome, next_step, rationale in (
            (True, "inconclusive", "iterate", "The five clean scans use different measurement conditions."),
            (False, "met", "design", "The full benchmark reached 90% against the comparable 80% baseline."),
        ):
            run, result, _ = record_external_run(db, human, document_id, confirmed["experiment_id"], clean=clean)
            decision = change(human, "decide", goal_id=goal["id"], brief_id=brief["brief_id"], revision=revision,
                              run_id=run, result_id=result, outcome=outcome, next_step=next_step, rationale=rationale)
            revision = decision["revision"]
    return goal["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--goals", action="store_true", help="Include ranked goals and feasibility decisions.")
    args = parser.parse_args()
    try:
        pilot = populate(args.database)
        goal_id = populate_goal_workflow(args.database, pilot) if args.goals else None
    except ValueError as error:
        parser.error(str(error))
    print(f"Human sign-in: {pilot['human_username']} / {pilot['human_password']}")
    print(f"Local AI application key: {pilot['ai_key']}")
    print(f"Research workspace: /documents?document={pilot['document']}&finding={pilot['conclusion']}")
    print(f"Findings: baseline #{pilot['baseline']}, full run #{pilot['full_run']}, "
          f"clean run #{pilot['clean_run']}, observation #{pilot['observation']}, conclusion #{pilot['conclusion']}")
    if goal_id is not None:
        print(f"Goal workflow: /documents?document={pilot['document']}&goal={goal_id}")


if __name__ == "__main__":
    main()
