"""Coordinate experiment work executed in the claimant's own environment."""

import json

from . import experiments, findings, sharing


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment_compute_tasks (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    creator_id INTEGER NOT NULL REFERENCES accounts(id),
    claimant_id INTEGER REFERENCES accounts(id),
    title TEXT NOT NULL,
    instructions TEXT NOT NULL,
    resources TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','claimed','complete','cancelled')),
    result TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS experiment_compute_tasks_experiment ON experiment_compute_tasks(experiment_id,id);
"""

ESTIMATES = {
    "cpu_cores": (1, 1_000_000), "ram_gib": (1, 1_000_000), "disk_gib": (1, 10_000_000),
    "wall_minutes": (1, 1_000_000), "gpu_count": (0, 100_000), "vram_gib_per_gpu": (0, 1_000_000),
}


def estimates(data):
    if not isinstance(data, dict) or data.keys() != ESTIMATES.keys():
        raise ValueError("Specify CPU, RAM, disk, wall time, and GPU estimates. Use zero for GPU and VRAM on CPU-only jobs.")
    for name, (minimum, maximum) in ESTIMATES.items():
        if type(data[name]) is not int or not minimum <= data[name] <= maximum:
            raise ValueError(f"Enter an integer from {minimum} to {maximum} for {name}.")
    if bool(data["gpu_count"]) != bool(data["vram_gib_per_gpu"]):
        raise ValueError("Set GPU count and per-GPU VRAM together, or use zero for both.")
    return json.dumps(data)


def actions_for(db, account, row):
    status = row["status"]
    creator = sharing.is_owner(db, account, row["creator_id"])
    claimant = row["claimant_id"] == account["id"]
    actions = []
    if status == "open":
        actions.append("claim")
    if status == "claimed":
        if claimant:
            actions.append("complete")
        if claimant or creator:
            actions.append("release")
    if creator and status in ("open", "claimed"):
        actions.append("cancel")
    return actions


def read(db, account, experiment_id):
    experiments.require_experiment(db, experiment_id, account)
    return {"tasks": [
        dict(row, resources=json.loads(row["resources"]), actions=actions_for(db, account, row))
        for row in db.execute("""
            SELECT t.*, creator.username AS creator, claimant.username AS claimant
            FROM experiment_compute_tasks t
            JOIN accounts creator ON creator.id=t.creator_id
            LEFT JOIN accounts claimant ON claimant.id=t.claimant_id
            WHERE t.experiment_id=? ORDER BY
               CASE t.status WHEN 'open' THEN 0 WHEN 'claimed' THEN 1 ELSE 2 END, t.id DESC
        """, (experiment_id,))
    ]}


def update(db, account, data):
    experiment_id = findings.positive_id(data.get("experiment_id"))
    action = data.get("action")
    experiments.require_experiment(db, experiment_id, account, edit=action == "create")
    if action == "create":
        title = experiments.validate_text(data.get("title"), "a title", 160, required=True).strip()
        instructions = experiments.validate_text(data.get("instructions"), "run instructions", 20000, required=True).strip()
        task_id = db.execute(
            "INSERT INTO experiment_compute_tasks(experiment_id,creator_id,title,instructions,resources) "
            "VALUES (?,?,?,?,?) RETURNING id",
            (experiment_id, account["id"], title, instructions, estimates(data.get("resources"))),
        ).fetchone()[0]
        return {"id": task_id, "revision": 1}

    task_id = findings.positive_id(data.get("id"))
    revision = findings.positive_id(data.get("revision"))
    row = db.execute("SELECT * FROM experiment_compute_tasks WHERE id=? AND experiment_id=?",
                     (task_id, experiment_id)).fetchone()
    if row is None:
        raise sharing.AccessDenied
    if row["revision"] != revision:
        raise sharing.EditConflict("This compute task changed. Reload it before trying again.")
    if action not in actions_for(db, account, row):
        raise sharing.AccessDenied
    status = {"claim": "claimed", "release": "open", "complete": "complete", "cancel": "cancelled"}[action]
    claimant = account["id"] if action == "claim" else None if action == "release" else row["claimant_id"]
    result = ""
    if action == "complete":
        result = experiments.validate_text(data.get("result"), "a result summary", 20000, required=True).strip()
    updated = db.execute(
        "UPDATE experiment_compute_tasks SET status=?,claimant_id=?,result=?,revision=revision+1 "
        "WHERE id=? AND revision=? RETURNING revision",
        (status, claimant, result, task_id, revision),
    ).fetchone()
    if updated is None:
        raise sharing.EditConflict("This compute task changed. Reload it before trying again.")
    return {"id": task_id, "revision": updated[0]}
