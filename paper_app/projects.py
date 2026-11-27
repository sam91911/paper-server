"""Shared research project repositories and proposed physical work."""

import json
import re

from . import experiments, sharing

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES accounts(id),
        title TEXT NOT NULL, description TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
        git_revision INTEGER NOT NULL DEFAULT 1, refs TEXT NOT NULL, pack BLOB NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0,1))
    )""",
    """CREATE TABLE IF NOT EXISTS project_members (
        project_id INTEGER NOT NULL REFERENCES projects(id), account_id INTEGER NOT NULL REFERENCES accounts(id),
        access TEXT NOT NULL CHECK(access IN ('read','write')), PRIMARY KEY(project_id,account_id)
    )""",
    """CREATE TABLE IF NOT EXISTS project_experiments (
        experiment_id INTEGER PRIMARY KEY REFERENCES experiments(id), project_id INTEGER NOT NULL REFERENCES projects(id)
    )""",
    """CREATE TABLE IF NOT EXISTS physical_proposals (
        id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES accounts(id),
        project_id INTEGER REFERENCES projects(id), title TEXT NOT NULL, plan TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1
    )""",
)
PLAN_FIELDS = ("procedure", "equipment", "procurement", "estimated_cost", "duration", "measurement", "expected_data")
MAX_BRANCHES = 100
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}")


def valid_branch(branch):
    return (isinstance(branch, str) and BRANCH.fullmatch(branch)
            and ".." not in branch and all(part and not part.startswith(".") and not part.endswith((".lock", "."))
                                           for part in branch.split("/")))


def scope(db, account, project_id, *, writing=False, managing=False):
    if type(project_id) is not int or not 0 < project_id < 2**63 or not account:
        raise sharing.AccessDenied
    row = db.execute("""SELECT p.id,p.owner_id,p.title,p.description,p.revision,p.git_revision,p.refs,
                               m.access FROM projects p LEFT JOIN project_members m
                               ON m.project_id=p.id AND m.account_id=? WHERE p.id=? AND p.deleted=0""",
                     (account["id"], project_id)).fetchone()
    if row is None or (row["owner_id"] != account["id"] and
                       (managing or row["access"] not in (("write",) if writing else ("read", "write")))):
        raise sharing.AccessDenied
    return row


def list_projects(db, account):
    return {"projects": [
        {key: row[key] for key in ("id", "title", "description", "revision", "access")}
        for row in db.execute("""SELECT p.id,p.title,p.description,p.revision,
                                  CASE WHEN p.owner_id=? THEN 'owner' ELSE m.access END AS access
                                 FROM projects p LEFT JOIN project_members m ON m.project_id=p.id AND m.account_id=?
                                 WHERE p.deleted=0 AND (p.owner_id=? OR m.access IS NOT NULL) ORDER BY p.id DESC""",
                              (account["id"], account["id"], account["id"]))
    ]}


def initialize(db):
    for statement in SCHEMA:
        db.execute(statement)
    if "deleted" not in {row["name"] for row in db.execute("PRAGMA table_info(projects)")}:
        db.execute("ALTER TABLE projects ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0,1))")


def default_branch(refs):
    return "main" if "main" in refs else next(iter(refs), None)


def detail(db, account, project_id):
    row = scope(db, account, project_id)
    result = {key: row[key] for key in ("id", "title", "description", "revision", "git_revision")}
    refs = json.loads(row["refs"])
    result.update(access="owner" if row["owner_id"] == account["id"] else row["access"],
                  branches=refs, default_branch=default_branch(refs), git_path=f"/git/projects/{project_id}.git")
    result["experiments"] = []
    for link in db.execute("SELECT experiment_id FROM project_experiments WHERE project_id=? ORDER BY experiment_id",
                           (project_id,)):
        try:
            experiment = experiments.require_experiment(db, link["experiment_id"], account)
        except (LookupError, sharing.AccessDenied):
            continue
        result["experiments"].append({"id": experiment["id"], "title": experiment["title"],
                                      "branch": f"experiment/{experiment['id']}"})
    if result["access"] == "owner":
        result["members"] = [dict(member) for member in db.execute(
            """SELECT a.username,m.access FROM project_members m JOIN accounts a ON a.id=m.account_id
               WHERE m.project_id=? ORDER BY a.username""", (project_id,))]
    return {"project": result}


def update(db, account, data):
    action, project_id = data.get("action"), data.get("id")
    if action == "create":
        title = experiments.validate_text(data.get("title"), "a title", 160, required=True)
        description = experiments.validate_text(data.get("description", ""), "a description", 20000)
        project_id = db.execute(
            "INSERT INTO projects(owner_id,title,description,refs,pack) VALUES (?,?,?,?,?) RETURNING id",
            (account["id"], title, description, "{}", b"")).fetchone()[0]
    elif action == "edit":
        row = scope(db, account, project_id, writing=True)
        if data.get("revision") != row["revision"]:
            raise sharing.EditConflict("The project changed. Reload it before saving.")
        title = experiments.validate_text(data.get("title"), "a title", 160, required=True)
        description = experiments.validate_text(data.get("description", ""), "a description", 20000)
        db.execute("UPDATE projects SET title=?,description=?,revision=revision+1 WHERE id=?",
                   (title, description, project_id))
    elif action == "delete":
        row = scope(db, account, project_id, managing=True)
        if data.get("revision") != row["revision"] or data.get("git_revision") != row["git_revision"]:
            raise sharing.EditConflict("The project changed. Reload it before deleting.")
        db.execute("UPDATE physical_proposals SET project_id=NULL,revision=revision+1 WHERE project_id=?", (project_id,))
        db.execute("DELETE FROM project_experiments WHERE project_id=?", (project_id,))
        db.execute("DELETE FROM project_members WHERE project_id=?", (project_id,))
        db.execute("DELETE FROM git_tokens WHERE kind='projects' AND resource_id=?", (project_id,))
        # Keep the ID reserved so old repository URLs cannot address a later project.
        db.execute("""UPDATE projects SET deleted=1,title='',description='',refs='{}',pack=?,
                      revision=revision+1,git_revision=git_revision+1 WHERE id=?""", (b"", project_id))
        return {"deleted_project_id": project_id}
    elif action == "share":
        from . import accounts
        row = scope(db, account, project_id, managing=True)
        member = db.execute("SELECT id FROM accounts WHERE username=? AND disabled_at IS NULL",
                            (accounts.identity(data.get("username")),)).fetchone()
        access = data.get("access")
        if not member or member["id"] == row["owner_id"] or access not in ("read", "write", "none"):
            raise ValueError("Choose a collaborator and access level.")
        if access == "none":
            db.execute("DELETE FROM project_members WHERE project_id=? AND account_id=?", (project_id, member["id"]))
        else:
            db.execute("""INSERT INTO project_members VALUES (?,?,?) ON CONFLICT(project_id,account_id)
                          DO UPDATE SET access=excluded.access""", (project_id, member["id"], access))
    elif action == "link_experiment":
        row = scope(db, account, project_id, writing=True)
        experiment_id = data.get("experiment_id")
        if type(experiment_id) is not int or not 0 < experiment_id < 2**63:
            raise ValueError("Choose a computational experiment.")
        experiment = experiments.require_experiment(db, experiment_id, account, edit=True)
        if experiment["owner_id"] != account["id"]:
            raise sharing.AccessDenied
        existing = db.execute("SELECT project_id FROM project_experiments WHERE experiment_id=?",
                              (experiment["id"],)).fetchone()
        if existing and existing["project_id"] != project_id:
            raise sharing.EditConflict("This experiment already belongs to another project.")
        if not existing:
            branch = f"experiment/{experiment['id']}"
            refs = json.loads(row["refs"])
            if branch in refs:
                raise sharing.EditConflict("The experiment branch already exists.")
            if len(refs) >= MAX_BRANCHES:
                raise ValueError(f"A project can have up to {MAX_BRANCHES} branches.")
            base = default_branch(refs)
            if base is None:
                raise sharing.EditConflict("Push the first project commit before creating an experiment branch.")
            refs[branch] = refs[base]
            db.execute("INSERT INTO project_experiments VALUES (?,?)", (experiment["id"], project_id))
            db.execute("UPDATE projects SET refs=?,git_revision=git_revision+1 WHERE id=?",
                       (json.dumps(refs), project_id))
    else:
        raise ValueError("Choose a project action.")
    return detail(db, account, project_id)


def proposals(db, account, *, proposal_id=None):
    result = []
    restriction = " AND f.id=?" if proposal_id is not None else ""
    args = (account["id"],) * 3 + ((proposal_id,) if proposal_id is not None else ())
    rows = db.execute(f"""SELECT f.*,p.owner_id AS project_owner,m.access FROM physical_proposals f
                          LEFT JOIN projects p ON p.id=f.project_id
                          LEFT JOIN project_members m ON m.project_id=p.id AND m.account_id=?
                          WHERE ((f.project_id IS NULL AND f.owner_id=?) OR p.owner_id=? OR m.access IS NOT NULL)
                          {restriction} ORDER BY f.id DESC""", args)
    for row in rows:
        editable = (row["project_id"] is None or row["project_owner"] == account["id"] or row["access"] == "write")
        result.append({"id": row["id"], "title": row["title"], "project_id": row["project_id"], "status": "proposed",
                       "revision": row["revision"], "editable": editable, **json.loads(row["plan"])})
    return {"proposals": result}


def save_proposal(db, account, data):
    proposal_id = data.get("id")
    if proposal_id is not None and (type(proposal_id) is not int or not 0 < proposal_id < 2**63):
        raise ValueError("Choose a proposal.")
    project_id = data.get("project_id")
    if project_id is not None:
        scope(db, account, project_id, writing=True)
    title = experiments.validate_text(data.get("title"), "a title", 160, required=True)
    plan = {key: experiments.validate_text(data.get(key), key.replace("_", " "), 12000, required=True)
            for key in PLAN_FIELDS}
    if proposal_id is None:
        proposal_id = db.execute("INSERT INTO physical_proposals(owner_id,project_id,title,plan) VALUES (?,?,?,?) RETURNING id",
                                 (account["id"], project_id, title, json.dumps(plan))).fetchone()[0]
    else:
        existing = proposals(db, account, proposal_id=proposal_id)["proposals"]
        if not existing or not existing[0]["editable"]:
            raise sharing.AccessDenied
        if data.get("revision") != existing[0]["revision"]:
            raise sharing.EditConflict("The proposal changed. Reload it before saving.")
        if project_id != existing[0]["project_id"]:
            raise ValueError("Keep the existing project association when editing a proposal.")
        db.execute("UPDATE physical_proposals SET title=?,plan=?,revision=revision+1 WHERE id=?",
                   (title, json.dumps(plan), proposal_id))
    return proposals(db, account, proposal_id=proposal_id)
