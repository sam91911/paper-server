"""Research priorities, experiment briefs, and evidence-backed decisions."""

import json

from . import experiments, findings, sharing

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS research_goals (
        id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
        author_id INTEGER NOT NULL REFERENCES accounts(id), author_role TEXT NOT NULL,
        question TEXT NOT NULL, rationale TEXT NOT NULL, uncertainty TEXT NOT NULL,
        priority INTEGER, selected INTEGER NOT NULL DEFAULT 0, deferred INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS goals_document ON research_goals(document_id,id)",
    """CREATE TABLE IF NOT EXISTS research_goal_evidence (
        goal_id INTEGER NOT NULL REFERENCES research_goals(id),
        finding_id INTEGER NOT NULL REFERENCES research_findings(id), PRIMARY KEY(goal_id,finding_id)
    )""",
    """CREATE TABLE IF NOT EXISTS research_goal_briefs (
        id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL REFERENCES research_goals(id),
        author_id INTEGER NOT NULL REFERENCES accounts(id), author_role TEXT NOT NULL,
        stage TEXT NOT NULL CHECK(stage IN ('feasibility','design')),
        approach TEXT NOT NULL, baseline_id INTEGER NOT NULL REFERENCES research_findings(id),
        criterion TEXT NOT NULL, conditions TEXT NOT NULL, budget TEXT NOT NULL,
        origin_decision_id INTEGER REFERENCES research_goal_decisions(id),
        experiment_id INTEGER UNIQUE REFERENCES experiments(id),
        confirmed_by INTEGER REFERENCES accounts(id), confirmed TEXT, baseline_snapshot TEXT,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS research_goal_decisions (
        id INTEGER PRIMARY KEY, brief_id INTEGER NOT NULL REFERENCES research_goal_briefs(id),
        run_id INTEGER NOT NULL UNIQUE REFERENCES experiment_runs(id),
        result_id INTEGER NOT NULL REFERENCES research_findings(id),
        author_id INTEGER NOT NULL REFERENCES accounts(id), outcome TEXT NOT NULL, next_step TEXT NOT NULL,
        rationale TEXT NOT NULL, evidence TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS research_goal_changes (
        goal_id INTEGER NOT NULL REFERENCES research_goals(id), revision INTEGER NOT NULL,
        actor_id INTEGER NOT NULL REFERENCES accounts(id), action TEXT NOT NULL,
        priority INTEGER, selected INTEGER NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(goal_id,revision)
    )""",
    "CREATE INDEX IF NOT EXISTS goal_briefs_goal ON research_goal_briefs(goal_id,id)",
    "CREATE INDEX IF NOT EXISTS goal_decisions_brief ON research_goal_decisions(brief_id,id)",
    "CREATE INDEX IF NOT EXISTS goal_evidence_finding ON research_goal_evidence(finding_id)",
    "CREATE INDEX IF NOT EXISTS goal_baseline_finding ON research_goal_briefs(baseline_id)",
    "CREATE INDEX IF NOT EXISTS goal_result_finding ON research_goal_decisions(result_id)",
)


def _text(data, name, limit=4000):
    return experiments.validate_text(data.get(name), name.replace("_", " "), limit, required=True)


def _evidence_ids(db, goal_id):
    return [row["finding_id"] for row in db.execute(
        "SELECT finding_id FROM research_goal_evidence WHERE goal_id=? ORDER BY finding_id", (goal_id,),
    )]


def _check_goal(db, account, row):
    findings.require_document(db, account, row["document_id"])
    for finding_id in _evidence_ids(db, row["id"]):
        findings.require_finding(db, account, row["document_id"], finding_id)


def require_goal(db, account, document_id, goal_id):
    row = db.execute("SELECT * FROM research_goals WHERE id=? AND document_id=?",
                     (findings.positive_id(goal_id), document_id)).fetchone()
    if row is None:
        raise sharing.AccessDenied
    _check_goal(db, account, row)
    return row


def discussion_ids(db, account, document_id):
    if account is None:
        return []
    rows = db.execute("""
        SELECT g.* FROM research_goals g WHERE (:doc IS NULL OR g.document_id=:doc)
        AND EXISTS (SELECT 1 FROM comments c WHERE c.goal_id=g.id)
    """, {"doc": document_id})
    visible = []
    for row in rows:
        try:
            _check_goal(db, account, row)
        except sharing.AccessDenied:
            continue
        visible.append(row["id"])
    return visible


def _check_decision(db, account, goal, row):
    experiments.require_run(db, row["run_id"], account)
    findings.require_finding(db, account, goal["document_id"], row["result_id"])
    for ref in json.loads(row["evidence"])["artifacts"]:
        version = db.execute("SELECT item_id,sha256 FROM research_versions WHERE id=?", (ref["id"],)).fetchone()
        if not version or version["sha256"] != ref["sha256"]:
            raise sharing.AccessDenied
        experiments.require_item(db, version["item_id"], account)


def _check_brief(db, account, goal, row):
    findings.require_finding(db, account, goal["document_id"], row["baseline_id"])
    if row["origin_decision_id"] is not None:
        origin = db.execute("SELECT * FROM research_goal_decisions WHERE id=?", (row["origin_decision_id"],)).fetchone()
        _check_decision(db, account, goal, origin)


def experiment_scope(db, account, experiment_id):
    """Enforce inherited goal and brief visibility for experiment, run, and file reads."""
    row = db.execute("SELECT * FROM research_goal_briefs WHERE experiment_id=?", (experiment_id,)).fetchone()
    if row is None:
        return None
    goal = db.execute("SELECT * FROM research_goals WHERE id=?", (row["goal_id"],)).fetchone()
    _check_goal(db, account, goal)
    _check_brief(db, account, goal, row)
    return row


def _brief_markdown(goal, brief):
    stage = brief["stage"].capitalize()
    baseline = f"Finding #{brief['baseline_id']}"
    if brief["baseline_snapshot"]:
        measure = json.loads(brief["baseline_snapshot"])
        baseline += f", revision {measure['revision']}\n\n{measure['statement']}"
        if measure["value"]:
            baseline += f"\n\n{measure['metric']}: {measure['value']} {measure['unit']} ({measure['conditions']})"
    markdown = (
        f"# {stage} brief #{brief['id']}\n\n{goal['question']}\n\n"
        f"## Uncertainty\n{goal['uncertainty']}\n\n"
        f"## Approach\n{brief['approach']}\n\n"
        f"## Baseline\n{baseline}\n\n"
        f"## Success criterion\n{brief['criterion']}\n\n"
        f"## Test conditions\n{brief['conditions']}\n\n"
        f"## Budget\n{brief['budget']}\n"
    )
    if brief["origin_decision_id"] is not None:
        markdown += f"\n## Supporting feasibility decision\nDecision #{brief['origin_decision_id']}\n"
    return markdown


def _record_change(db, account, goal, action, *, priority=None, selected=None, deferred=None):
    priority = goal["priority"] if priority is None else priority
    selected = goal["selected"] if selected is None else int(selected)
    deferred = goal["deferred"] if deferred is None else deferred
    revision = goal["revision"] + 1
    db.execute("UPDATE research_goals SET priority=?,selected=?,deferred=?,revision=? WHERE id=?",
               (priority, selected, deferred, revision, goal["id"]))
    db.execute("INSERT INTO research_goal_changes(goal_id,revision,actor_id,action,priority,selected) VALUES (?,?,?,?,?,?)",
               (goal["id"], revision, account["id"], action, priority, selected))
    return revision


def _proposal(db, account, document, data):
    ids = data.get("evidence_ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 20:
        raise ValueError("Choose between 1 and 20 supporting findings.")
    ids = list(dict.fromkeys(findings.positive_id(value) for value in ids))
    for finding_id in ids:
        findings.require_finding(db, account, document["id"], finding_id)
    goal_id = db.execute(
        "INSERT INTO research_goals(document_id,author_id,author_role,question,rationale,uncertainty) VALUES (?,?,?,?,?,?) RETURNING id",
        (document["id"], account["id"], account["role"], _text(data, "question", 160),
         _text(data, "rationale"), _text(data, "uncertainty")),
    ).fetchone()[0]
    db.executemany("INSERT INTO research_goal_evidence(goal_id,finding_id) VALUES (?,?)",
                   [(goal_id, finding_id) for finding_id in ids])
    return {"id": goal_id, "revision": 1}


def _draft(db, account, goal, data):
    if not goal["selected"]:
        raise ValueError("Select the goal before drafting a brief.")
    baseline = findings.require_finding(db, account, goal["document_id"], data.get("baseline_id"))
    values = tuple(_text(data, name) for name in ("approach", "criterion", "conditions", "budget"))
    brief_id = db.execute("""
        INSERT INTO research_goal_briefs(goal_id,author_id,author_role,stage,baseline_id,approach,criterion,conditions,budget)
        VALUES (?,?,?,'feasibility',?,?,?,?,?)
        RETURNING id
    """, (goal["id"], account["id"], account["role"], baseline["id"], *values)).fetchone()[0]
    return {"id": goal["id"], "brief_id": brief_id}


def _confirm(db, account, document, goal, brief):
    if brief["experiment_id"] is not None:
        raise sharing.EditConflict("This brief is already confirmed.")
    baseline = findings.require_finding(db, account, goal["document_id"], brief["baseline_id"])
    if any(ref.get("stale") for ref in baseline["evidence"]):
        raise ValueError("Review the baseline citations before confirming this brief.")
    snapshot = json.dumps(_measurement(baseline))
    experiment_id = experiments.save_experiment(db, account, {
        "title": goal["question"], "description": brief["approach"], "audience": document["audience"],
        "research_document_id": document["id"],
    })
    # Users who enter through the workspace use its live sharing rules. Write
    # access still comes from the experiment owner and explicit editor grants.
    db.execute("""
        UPDATE research_goal_briefs SET experiment_id=?,confirmed_by=?,confirmed=CURRENT_TIMESTAMP,baseline_snapshot=?
        WHERE id=?
    """, (experiment_id, account["id"], snapshot, brief["id"]))
    revision = _record_change(db, account, goal, "confirm")
    return {"id": goal["id"], "brief_id": brief["id"], "experiment_id": experiment_id, "revision": revision}


def _measurement(finding):
    return {name: finding[name] for name in ("id", "revision", "statement", "metric", "value", "unit", "conditions")}


def _decision(db, account, goal, brief, data):
    run = experiments.require_run(db, findings.positive_id(data.get("run_id")), account)
    if brief["experiment_id"] is None or run["experiment_id"] != brief["experiment_id"]:
        raise ValueError("Choose a run that tested this confirmed brief.")
    if run["status"] not in ("complete", "failed"):
        raise ValueError("Record an outcome after the run completes or fails.")
    if db.execute("SELECT 1 FROM research_goal_decisions WHERE run_id=?", (run["id"],)).fetchone():
        raise sharing.EditConflict("A decision already exists for this run.")
    baseline = findings.require_finding(db, account, goal["document_id"], brief["baseline_id"])
    result = findings.require_finding(db, account, goal["document_id"], data.get("result_id"))
    artifact_refs = [ref for ref in result["evidence"] if ref["kind"] == "run_artifact"]
    if (result["kind"] != "run_result" or not artifact_refs
            or any(ref["run_id"] != run["id"] for ref in artifact_refs)):
        raise ValueError("Choose a run result citing an uploaded artifact from this run.")
    artifacts = [{"id": ref["id"], "sha256": ref["sha256"]} for ref in artifact_refs]
    for ref in artifacts:
        experiments.version_content(db, account, ref["id"])
    original = json.loads(brief["baseline_snapshot"])
    comparison = findings.compare(dict(original, evidence=baseline["evidence"]), result)
    stale = any(ref.get("stale") for item in (baseline, result) for ref in item["evidence"])
    outcome, next_step = data.get("outcome"), data.get("next_step")
    if outcome not in ("met", "missed", "inconclusive") or next_step not in ("iterate", "design", "set_aside"):
        raise ValueError("Choose an outcome and a next step.")
    mismatch = (bool(original["value"]) != bool(result["value"])
                or (original["value"] and result["value"] and comparison["reasons"]))
    changed = baseline["revision"] != original["revision"]
    failed = run["status"] == "failed"
    different_test = bool(result["value"]) and result["conditions"] != brief["conditions"]
    if changed:
        comparison["reasons"].append("The baseline finding changed after confirmation.")
    if failed:
        comparison["reasons"].append("The run failed.")
    if different_test:
        comparison["reasons"].append("The run's measurement conditions differ from the confirmed brief.")
    if stale or mismatch or changed or failed or different_test:
        comparison["difference"] = None
        if outcome != "inconclusive":
            raise ValueError("Record this run as inconclusive because the evidence cannot be compared or the run failed.")
    if next_step == "design" and (outcome != "met" or brief["stage"] != "feasibility"):
        raise ValueError("A full design requires a feasibility run that met its criterion.")
    rationale = _text(data, "rationale")
    snapshot = {"artifacts": artifacts, "comparison": comparison, "baseline": original,
                "result": _measurement(result),
                "run": {key: run[key] for key in ("id", "revision", "status", "methods", "settings")}}
    decision_id = db.execute("""
        INSERT INTO research_goal_decisions(brief_id,run_id,result_id,author_id,outcome,next_step,rationale,evidence)
        VALUES (?,?,?,?,?,?,?,?)
        RETURNING id
    """, (brief["id"], run["id"], result["id"], account["id"], outcome, next_step,
          rationale, json.dumps(snapshot))).fetchone()[0]
    if next_step == "design":
        db.execute("""
            INSERT INTO research_goal_briefs(goal_id,author_id,author_role,stage,approach,baseline_id,criterion,
                                             conditions,budget,origin_decision_id)
            VALUES (?,?,?,'design',?,?,?,?,?,?)
        """, (goal["id"], account["id"], account["role"], brief["approach"], brief["baseline_id"],
              brief["criterion"], brief["conditions"], brief["budget"], decision_id))
    if next_step == "set_aside":
        revision = _record_change(db, account, goal, "set_aside", selected=0, deferred=1)
    else:
        revision = _record_change(db, account, goal, "decide")
    return {"id": goal["id"], "decision_id": decision_id, "revision": revision}


def update(db, account, data):
    document = findings.require_document(db, account, data.get("document_id"))
    action = data.get("action")
    if action == "propose":
        return _proposal(db, account, document, data)
    goal = require_goal(db, account, document["id"], data.get("goal_id"))
    if action == "draft":
        return _draft(db, account, goal, data)
    if account["role"] not in ("user", "member") or not sharing.is_owner(db, account, document["owner_id"]):
        raise sharing.AccessDenied
    if data.get("revision") != goal["revision"]:
        raise sharing.EditConflict("This goal changed. Reload it before saving.")
    if action == "rank":
        priority = findings.positive_id(data.get("priority"))
        selected = data.get("selected")
        if priority > 1000000 or type(selected) is not bool:
            raise ValueError("Choose a priority from 1 to 1,000,000 and a selection state.")
        revision = _record_change(db, account, goal, action, priority=priority, selected=selected,
                                  deferred=0 if selected else None)
        return {"id": goal["id"], "revision": revision}
    if action not in ("confirm", "decide", "revise_design"):
        raise ValueError("Choose a goal action.")
    brief = db.execute("SELECT * FROM research_goal_briefs WHERE id=? AND goal_id=?",
                       (findings.positive_id(data.get("brief_id")), goal["id"])).fetchone()
    if brief is None:
        raise sharing.AccessDenied
    _check_brief(db, account, goal, brief)
    if action == "decide":
        return _decision(db, account, goal, brief, data)
    if not goal["selected"]:
        raise ValueError("Select the goal before continuing with this brief.")
    if action == "confirm":
        return _confirm(db, account, document, goal, brief)
    if brief["stage"] != "design":
        raise ValueError("Choose a full design brief.")
    baseline = findings.require_finding(db, account, document["id"], data.get("baseline_id"))
    values = tuple(_text(data, name) for name in ("approach", "criterion", "conditions", "budget"))
    new_id = db.execute("""
        INSERT INTO research_goal_briefs(goal_id,author_id,author_role,stage,approach,criterion,
                                         conditions,budget,baseline_id,origin_decision_id)
        VALUES (?,?,?,'design',?,?,?,?,?,?)
        RETURNING id
    """, (goal["id"], account["id"], account["role"], *values, baseline["id"], brief["origin_decision_id"])).fetchone()[0]
    return {"id": goal["id"], "brief_id": new_id}


def read(db, account, document_id):
    document = findings.require_document(db, account, document_id)
    manager = account["role"] in ("user", "member") and sharing.is_owner(db, account, document["owner_id"])
    available = []
    for goal in db.execute("""
        SELECT g.*, COALESCE(NULLIF(a.display_name,''),a.username) AS author_name
        FROM research_goals g JOIN accounts a ON a.id=g.author_id WHERE g.document_id=?
        ORDER BY g.deferred,g.priority IS NULL,g.priority,g.id
    """, (document_id,)):
        try:
            _check_goal(db, account, goal)
        except sharing.AccessDenied:
            continue
        briefs = []
        for brief in db.execute("""
            SELECT b.*, COALESCE(NULLIF(a.display_name,''),a.username) AS author_name
            FROM research_goal_briefs b JOIN accounts a ON a.id=b.author_id WHERE b.goal_id=? ORDER BY b.id DESC
        """, (goal["id"],)):
            try:
                _check_brief(db, account, goal, brief)
                if brief["experiment_id"] is not None:
                    experiments.require_experiment(db, brief["experiment_id"], account)
            except sharing.AccessDenied:
                continue
            runs, decisions = [], []
            if brief["experiment_id"] is not None:
                for run in db.execute("SELECT * FROM experiment_runs WHERE experiment_id=? ORDER BY id DESC",
                                      (brief["experiment_id"],)):
                    if experiments.allowed(db, "run", run, account):
                        runs.append({name: run[name] for name in ("id", "title", "status")})
            for row in db.execute("""
                SELECT d.*, COALESCE(NULLIF(a.display_name,''),a.username) AS author_name
                FROM research_goal_decisions d JOIN accounts a ON a.id=d.author_id WHERE d.brief_id=? ORDER BY d.id DESC
            """, (brief["id"],)):
                try:
                    _check_decision(db, account, goal, row)
                except sharing.AccessDenied:
                    continue
                decisions.append(dict(row, evidence=json.loads(row["evidence"])))
            briefs.append(dict(brief, markdown=_brief_markdown(goal, brief), runs=runs, decisions=decisions))
        # Keep the workspace revision and its priority history available to managers.
        row = dict(goal, evidence_ids=_evidence_ids(db, goal["id"]), briefs=briefs)
        if manager:
            row["priority_history"] = [dict(change) for change in db.execute(
                "SELECT * FROM research_goal_changes WHERE goal_id=? AND action='rank' ORDER BY revision DESC",
                (goal["id"],),
            )]
        else:
            row.pop("priority")
            row.pop("revision")
        available.append(row)
    return {"goals": available, "can_manage": manager,
            "findings": [{"id": item["id"], "statement": item["statement"], "kind": item["kind"],
                          "conditions": item["conditions"],
                          "run_ids": sorted({ref["run_id"] for ref in item["evidence"] if ref["kind"] == "run_artifact"})}
                         for item in findings.visible(db, account, document_id)]}
