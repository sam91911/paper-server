"""Curated tools and bounded host capability discovery."""
import json
import re
import shutil
import subprocess

from . import experiments, sharing

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_tools (
 id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES accounts(id), name TEXT NOT NULL,
 version TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', instructions TEXT NOT NULL DEFAULT '',
 audience TEXT NOT NULL DEFAULT 'owner', image_digest TEXT NOT NULL, command_json TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tool_approvers (account_id INTEGER PRIMARY KEY REFERENCES accounts(id));
CREATE TABLE IF NOT EXISTS tool_jobs (
 id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id),
 run_id INTEGER NOT NULL REFERENCES experiment_runs(id), tool_id INTEGER NOT NULL REFERENCES research_tools(id),
 requester_id INTEGER NOT NULL REFERENCES accounts(id), approver_id INTEGER REFERENCES accounts(id),
 request_json TEXT NOT NULL, request_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 log TEXT NOT NULL DEFAULT '', created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
HOST_TOOLS = {'pdftotext': ('pdftotext', '-v'), 'python3': ('python3', '--version'),
              'llama-completion': ('llama-completion', '--version'), 'podman': ('podman', '--version')}


def host_tools():
    results = []
    for name, command in HOST_TOOLS.items():
        path = shutil.which(command[0])
        entry = {'name': name, 'available': bool(path), 'version': ''}
        if path:
            try:
                result = subprocess.run([path, *command[1:]], stdin=subprocess.DEVNULL, capture_output=True, timeout=3)
                entry['version'] = (result.stdout + result.stderr)[:1000].decode('utf-8', 'replace').split('\n')[0]
            except (OSError, subprocess.SubprocessError):
                entry['version'] = 'unavailable'
        results.append(entry)
    return results


def register(db, owner, data):
    name = experiments.validate_text(data.get('name'), 'a name', 160, required=True)
    version = experiments.validate_text(data.get('version', ''), 'a version', 160)
    description = experiments.validate_text(data.get('description', ''), 'a description', 20000)
    instructions = experiments.validate_text(data.get('instructions', ''), 'instructions', 20000)
    image = data.get('image_digest', '')
    if not isinstance(image, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}', image):
        raise ValueError('Use a fixed container image reference with a sha256 digest.')
    command = data.get('command')
    if not isinstance(command, list) or not command or len(command) > 20 or any(
        not isinstance(x, str) or not x or len(x) > 1000 or '\x00' in x for x in command
    ):
        raise ValueError('Provide a fixed executable and argument list.')
    audience = sharing.validate_audience(data.get('audience', 'owner'))
    return db.execute('INSERT INTO research_tools(owner_id,name,version,description,instructions,audience,image_digest,command_json) VALUES (?,?,?,?,?,?,?,?)',
                      (owner['id'], name, version, description, instructions, audience, image, json.dumps(command))).lastrowid


def require_tool(db, tool_id, account):
    row = db.execute('SELECT * FROM research_tools WHERE id=?', (tool_id,)).fetchone()
    if not row or not experiments.allowed(db, 'tool', row, account):
        raise sharing.AccessDenied
    return row


def list_tools(db, account):
    return [dict(row, command=json.loads(row['command_json'])) for row in db.execute('SELECT * FROM research_tools ORDER BY name,id')
            if experiments.allowed(db, 'tool', row, account)]


def create_job(db, account, data):
    import hashlib
    run_id, tool_id = data.get('run_id'), data.get('tool_id')
    if type(run_id) is not int or type(tool_id) is not int:
        raise ValueError('Choose a run and a tool.')
    run = experiments.require_run(db, run_id, account, edit=True)
    tool = require_tool(db, tool_id, account)
    versions = data.get('version_ids', [])
    if not isinstance(versions, list) or len(versions) > 20 or any(type(v) is not int or v <= 0 for v in versions) or len(set(versions)) != len(versions):
        raise ValueError('Choose up to 20 distinct file versions.')
    inputs = []
    for version_id in versions:
        version = db.execute('SELECT id,item_id,filename,sha256 FROM research_versions WHERE id=?', (version_id,)).fetchone()
        if not version or not version['sha256']:
            raise ValueError('Inputs must be stored file versions.')
        item = experiments.require_item(db, version['item_id'], account)
        if item['experiment_id'] != run['experiment_id']:
            raise sharing.AccessDenied
        inputs.append(dict(version))
    spec = {'tool_id': tool_id, 'tool_revision': tool['revision'], 'image': tool['image_digest'],
            'command': json.loads(tool['command_json']), 'inputs': inputs}
    request = json.dumps(spec, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(request.encode()).hexdigest()
    return db.execute('INSERT INTO tool_jobs(experiment_id,run_id,tool_id,requester_id,request_json,request_hash) VALUES (?,?,?,?,?,?)',
                      (run['experiment_id'], run_id, tool_id, account['id'], request, digest)).lastrowid


def approve_job(db, approver, job_id):
    import hashlib
    if approver['role'] != 'user' or not db.execute('SELECT 1 FROM tool_approvers WHERE account_id=?', (approver['id'],)).fetchone():
        raise sharing.AccessDenied
    job = db.execute('SELECT * FROM tool_jobs WHERE id=?', (job_id,)).fetchone()
    if not job or job['status'] != 'pending' or job['requester_id'] == approver['id']:
        raise sharing.AccessDenied
    experiments.require_run(db, job['run_id'], approver)
    require_tool(db, job['tool_id'], approver)
    spec = json.loads(job['request_json'])
    if hashlib.sha256(job['request_json'].encode()).hexdigest() != job['request_hash']:
        raise ValueError('The job request changed.')
    requester_row = db.execute(f"SELECT a.id,a.username,{experiments.accounts.ROLE_SQL.format(alias='a')} role FROM accounts a WHERE a.id=?", (job['requester_id'],)).fetchone()
    requester = dict(requester_row) if requester_row else None
    experiments.require_run(db, job['run_id'], requester, edit=True)
    tool = require_tool(db, job['tool_id'], requester)
    if tool['revision'] != spec['tool_revision'] or tool['image_digest'] != spec['image'] or json.loads(tool['command_json']) != spec['command']:
        raise ValueError('The tool changed; submit a new request.')
    for item in spec['inputs']:
        version = db.execute('SELECT * FROM research_versions WHERE id=?', (item['id'],)).fetchone()
        if not version or version['sha256'] != item['sha256']:
            raise ValueError('An input changed; submit a new request.')
        experiments.require_item(db, version['item_id'], requester)
        experiments.require_item(db, version['item_id'], approver)
    db.execute("UPDATE tool_jobs SET status='approved',approver_id=?,updated=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (approver['id'], job_id))
