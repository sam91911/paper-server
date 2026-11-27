"""Experiments, runs and immutable, access-controlled research artifacts."""
import hashlib
import json
import re
import stat
import struct
import zlib
from io import BytesIO
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from . import accounts, sharing

MAX_FILE_BYTES = 100 * 1024 * 1024
KINDS = ('code', 'environment', 'equipment', 'tool_record', 'data')
VERSION_BATCH_SIZE = 500
REPRODUCTION_OUTCOMES = ('matched', 'different', 'inconclusive')
MAX_ARCHIVE_ENTRIES = 5_000
MAX_ARCHIVE_DIRECTORY_BYTES = 4 * 1024 * 1024
GRANT_SCOPES = {
    'experiment': ('experiments', 'id'),
    'run': ('experiment_runs', 'experiment_id'),
    'item': ('research_items', 'experiment_id'),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
 id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES accounts(id), title TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', paper_id INTEGER REFERENCES papers(id),
 audience TEXT NOT NULL DEFAULT 'owner', revision INTEGER NOT NULL DEFAULT 1,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS experiment_runs (
 id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id),
 owner_id INTEGER NOT NULL REFERENCES accounts(id), title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'planned', audience TEXT NOT NULL DEFAULT 'owner', revision INTEGER NOT NULL DEFAULT 1,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS run_reproductions (
 run_id INTEGER NOT NULL REFERENCES experiment_runs(id), run_revision INTEGER NOT NULL,
 reviewer_id INTEGER NOT NULL REFERENCES accounts(id),
 outcome TEXT NOT NULL CHECK(outcome IN ('matched','different','inconclusive')),
 observed TEXT NOT NULL, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(run_id,run_revision,reviewer_id)
);
CREATE TABLE IF NOT EXISTS research_items (
 id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id),
 run_id INTEGER REFERENCES experiment_runs(id), owner_id INTEGER NOT NULL REFERENCES accounts(id),
 kind TEXT NOT NULL CHECK(kind IN ('code','environment','equipment','tool_record','data')),
 title TEXT NOT NULL, audience TEXT NOT NULL DEFAULT 'owner', revision INTEGER NOT NULL DEFAULT 1,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS research_versions (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES research_items(id),
 number INTEGER NOT NULL, creator_id INTEGER NOT NULL REFERENCES accounts(id),
 description TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL DEFAULT '',
 external_ref TEXT NOT NULL DEFAULT '', sha256 TEXT, content BLOB,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(item_id,number)
);
CREATE TABLE IF NOT EXISTS research_grants (
 kind TEXT NOT NULL CHECK(kind IN ('experiment','run','item','tool')),
 item_id INTEGER NOT NULL, account_id INTEGER NOT NULL REFERENCES accounts(id),
 can_edit INTEGER NOT NULL DEFAULT 0 CHECK(can_edit IN (0,1)),
 PRIMARY KEY(kind,item_id,account_id)
);
CREATE INDEX IF NOT EXISTS research_runs_experiment ON experiment_runs(experiment_id,id);
CREATE INDEX IF NOT EXISTS research_items_experiment ON research_items(experiment_id,run_id,id);
"""


def validate_text(value, name, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'Enter {name} of up to {limit} characters.')
    return value.strip() if required else value


def _grant(db, kind, item_id, account, edit=False):
    if not account:
        return False
    row = db.execute('SELECT can_edit FROM research_grants WHERE kind=? AND item_id=? AND account_id=?',
                     (kind, item_id, account['id'])).fetchone()
    return bool(row and (not edit or row['can_edit']))


def allowed(db, kind, row, account, *, edit=False):
    if not account:
        return False
    if sharing.is_owner(db, account, row['owner_id']):
        return True
    if _grant(db, kind, row['id'], account, edit=edit):
        return True
    return not edit and _audience_allows(row['audience'], account['role'])


def _audience_allows(audience, role):
    return ((audience == 'users' and role == 'user') or
            (audience == 'local' and role in ('user', 'local')) or
            (audience == 'all' and role in ('user', 'local', 'cloud')) or
            (audience == 'ai' and role == 'local'))


def require_experiment(db, experiment_id, account, *, edit=False):
    row = db.execute("""
        SELECT e.*, b.id AS goal_brief_id, git.head AS source_commit FROM experiments e
        LEFT JOIN research_goal_briefs b ON b.experiment_id=e.id
        LEFT JOIN git_repository_state git ON git.kind='experiments' AND git.resource_id=e.id
        WHERE e.id=?
    """, (experiment_id,)).fetchone()
    if not row or not account:
        raise sharing.AccessDenied
    if row['goal_brief_id'] is not None:
        from . import goals
        goals.experiment_scope(db, account, experiment_id)
        if not edit:
            return row
    if not allowed(db, 'experiment', row, account, edit=edit):
        raise sharing.AccessDenied
    return row


def require_run(db, run_id, account, *, edit=False):
    row = db.execute('SELECT * FROM experiment_runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise sharing.AccessDenied
    require_experiment(db, row['experiment_id'], account, edit=edit)
    if not allowed(db, 'run', row, account, edit=edit):
        raise sharing.AccessDenied
    return row


def require_item(db, item_id, account, *, edit=False):
    row = db.execute('SELECT * FROM research_items WHERE id=?', (item_id,)).fetchone()
    if not row:
        raise sharing.AccessDenied
    require_experiment(db, row['experiment_id'], account, edit=edit)
    if row['run_id'] is not None:
        require_run(db, row['run_id'], account, edit=edit)
    if not allowed(db, 'item', row, account, edit=edit):
        raise sharing.AccessDenied
    return row


def set_grants(db, kind, item_id, actor, row, readers, editors):
    if not sharing.is_owner(db, actor, row['owner_id']):
        raise sharing.AccessDenied
    if not isinstance(readers, list) or not isinstance(editors, list) or len(readers) + len(editors) > 100:
        raise ValueError('Choose up to 100 readers and editors.')
    reader_ids = sharing.recipient_ids(db, readers) or []
    editor_ids = sharing.recipient_ids(db, editors) or []
    db.execute('DELETE FROM research_grants WHERE kind=? AND item_id=?', (kind, item_id))
    db.executemany('INSERT INTO research_grants VALUES (?,?,?,?)',
                   ((kind, item_id, i, int(i in editor_ids)) for i in sorted(set(reader_ids + editor_ids))))


def _read_grants(db, kind, account, experiment_id=None):
    """Collect the viewer's direct grants and the sharing names they own."""
    table, scope_column = GRANT_SCOPES[kind]
    scope = '' if experiment_id is None else f' AND r.{scope_column}=:experiment_id'
    rows = db.execute(
        f"SELECT g.item_id,g.account_id,g.can_edit,{sharing.owner_sql('r.owner_id')} AS owned,a.username "
        f'FROM research_grants g JOIN {table} r ON r.id=g.item_id '
        'JOIN accounts a ON a.id=g.account_id '
        f"WHERE g.kind=:kind AND ({sharing.owner_sql('r.owner_id')} OR g.account_id=:viewer)"
        + scope + ' ORDER BY a.username',
        sharing.viewer_params(account, kind=kind, experiment_id=experiment_id),
    )
    direct = {}
    names = {}
    for row in rows:
        item_id = row['item_id']
        if row['account_id'] == account['id']:
            direct[item_id] = bool(row['can_edit'])
        if row['owned']:
            groups = names.setdefault(item_id, {'readers': [], 'editors': []})
            groups['editors' if row['can_edit'] else 'readers'].append(row['username'])
    return direct, names


def _visible_rows(rows, account, grants, *, inherited=False):
    direct, names = grants
    for row in rows:
        owned = bool(row['owned'])
        if (owned or row['id'] in direct or _audience_allows(row['audience'], account['role'])
                or (inherited and row['goal_brief_id'] is not None)):
            item = dict(row)
            del item['owned']
            if owned:
                item.update(names.get(row['id'], {'readers': [], 'editors': []}))
            yield item, owned


def _audience(value):
    return sharing.validate_audience(value if value is not None else 'owner')


def save_experiment(db, account, data):
    item_id = data.get('id')
    row = require_experiment(db, item_id, account, edit=True) if item_id is not None else None
    title = validate_text(data.get('title', row['title'] if row else None), 'a title', 160, required=True)
    description = validate_text(data.get('description', row['description'] if row else ''), 'a description', 20000)
    audience = _audience(data.get('audience', row['audience'] if row else None))
    paper_id = data.get('paper_id', row['paper_id'] if row else None)
    if 'paper_id' in data and paper_id is not None:
        if type(paper_id) is not int:
            raise ValueError('Choose a paper.')
        sharing.paper_for(db, paper_id, account)
    document_id = data.get('research_document_id', row['research_document_id'] if row else None)
    if row and row['goal_brief_id'] is not None and document_id != row['research_document_id']:
        raise ValueError('This experiment belongs to a confirmed research brief.')
    if 'research_document_id' in data and document_id is not None:
        if type(document_id) is not int or not 0 < document_id < 2**63:
            raise ValueError('Choose a research document.')
        document = sharing.document_for(db, account, document_id)
        if not document or document["kind"] != "document":
            raise sharing.AccessDenied
    if item_id is None:
        item_id = db.execute(
            'INSERT INTO experiments(owner_id,title,description,paper_id,audience,research_document_id) VALUES (?,?,?,?,?,?) RETURNING id',
            (account['id'], title, description, paper_id, audience, document_id),
        ).fetchone()[0]
    else:
        if data.get('revision') != row['revision']:
            raise sharing.EditConflict('This experiment changed. Reload it before saving.')
        if audience != row['audience'] and not sharing.is_owner(db, account, row['owner_id']):
            raise sharing.AccessDenied
        db.execute('UPDATE experiments SET title=?,description=?,paper_id=?,audience=?,research_document_id=?,'
                   'revision=revision+1,updated=CURRENT_TIMESTAMP WHERE id=?',
                   (title, description, paper_id, audience, document_id, item_id))
    return item_id


def reproduction_record(value):
    if not isinstance(value, dict) or value.keys() - {'dependencies', 'inputs', 'seed', 'expected_output'}:
        raise ValueError('Use a reproduction record with dependencies, inputs, seed, and expected output.')
    dependencies = value.get('dependencies', [])
    inputs = value.get('inputs', [])
    if not isinstance(dependencies, list) or len(dependencies) > 100:
        raise ValueError('Record up to 100 dependency versions.')
    if not isinstance(inputs, list) or len(inputs) > 100:
        raise ValueError('Record up to 100 input checksums.')
    versions = [validate_text(entry, 'a dependency version', 512, required=True) for entry in dependencies]
    if any('\r' in version or '\n' in version for version in versions):
        raise ValueError('Enter one dependency version per entry.')
    checksums = {}
    for entry in inputs:
        if not isinstance(entry, dict) or entry.keys() != {'name', 'sha256'}:
            raise ValueError('Each input needs a name and SHA-256 checksum.')
        name = validate_text(entry['name'], 'an input name', 512, required=True)
        if '\r' in name or '\n' in name:
            raise ValueError('Enter a single-line name for each input.')
        digest = entry['sha256']
        if not isinstance(digest, str) or not re.fullmatch(r'[A-Fa-f0-9]{64}', digest):
            raise ValueError('Use a 64-character hexadecimal SHA-256 checksum.')
        if name in checksums:
            raise ValueError('Each input name must be unique.')
        checksums[name] = digest.lower()
    record = {
        'dependencies': versions,
        'inputs': [{'name': name, 'sha256': digest} for name, digest in checksums.items()],
        'seed': validate_text(value.get('seed', ''), 'a seed', 200).strip(),
        'expected_output': validate_text(value.get('expected_output', ''), 'expected output', 10000).strip(),
    }
    return {key: entry for key, entry in record.items() if entry}


def save_run(db, account, data):
    experiment_id = data.get('experiment_id')
    experiment = require_experiment(db, experiment_id, account, edit=True)
    title = validate_text(data.get('title'), 'a title', 160, required=True)
    description = validate_text(data.get('description', ''), 'a description', 20000)
    status = data.get('status', 'planned')
    if status not in ('planned', 'running', 'complete', 'failed'):
        raise ValueError('Choose a valid run status.')
    audience = _audience(data.get('audience'))
    run_id = data.get('id')
    row = require_run(db, run_id, account, edit=True) if run_id is not None else None
    brief = None
    if row is None and experiment['goal_brief_id'] is not None:
        brief = db.execute("SELECT approach,conditions FROM research_goal_briefs WHERE id=?",
                           (experiment['goal_brief_id'],)).fetchone()
    if row:
        default_methods, default_settings = row['methods'], row['settings']
    elif brief:
        default_methods, default_settings = brief['approach'], brief['conditions']
    else:
        default_methods = default_settings = ''
    methods = validate_text(data.get('methods', default_methods), 'methods', 20000)
    settings = validate_text(data.get('settings', default_settings), 'settings', 20000)
    reproduction = row['reproduction'] if row else '{}'
    if 'reproduction' in data:
        reproduction = json.dumps(reproduction_record(data['reproduction']))
    if run_id is None:
        return db.execute(
            'INSERT INTO experiment_runs(experiment_id,owner_id,title,description,status,audience,methods,settings,reproduction)'
            ' VALUES (?,?,?,?,?,?,?,?,?) RETURNING id',
            (experiment_id, account['id'], title, description, status, audience, methods, settings, reproduction),
        ).fetchone()[0]
    if row['experiment_id'] != experiment_id:
        raise sharing.AccessDenied
    if data.get('revision') != row['revision']:
        raise sharing.EditConflict('This run changed. Reload it before saving.')
    if audience != row['audience'] and not sharing.is_owner(db, account, row['owner_id']):
        raise sharing.AccessDenied
    db.execute('UPDATE experiment_runs SET title=?,description=?,status=?,audience=?,methods=?,settings=?,reproduction=?,'
               'revision=revision+1,updated=CURRENT_TIMESTAMP WHERE id=?',
               (title, description, status, audience, methods, settings, reproduction, run_id))
    return run_id


def can_verify_run(account, run, *, owned):
    return account['role'] in ('user', 'member') and run['status'] == 'complete' and not owned


def verify_run(db, account, data):
    run_id, revision = data.get('run_id'), data.get('run_revision')
    if any(type(value) is not int or not 0 < value < 2**63 for value in (run_id, revision)):
        raise ValueError('Choose a run and its revision.')
    run = require_run(db, run_id, account)
    if not can_verify_run(account, run, owned=sharing.is_owner(db, account, run['owner_id'])):
        raise sharing.AccessDenied
    if revision != run['revision']:
        raise sharing.EditConflict('This run changed. Reload it before recording a rerun.')
    outcome = data.get('outcome')
    if outcome not in REPRODUCTION_OUTCOMES:
        raise ValueError('Choose a rerun outcome.')
    observed = validate_text(data.get('observed'), 'the observed result', 10000, required=True)
    if '\0' in observed:
        raise ValueError('Enter the observed result as text.')
    db.execute(
        'INSERT INTO run_reproductions(run_id,run_revision,reviewer_id,outcome,observed) VALUES (?,?,?,?,?) '
        'ON CONFLICT(run_id,run_revision,reviewer_id) DO UPDATE SET '
        'outcome=excluded.outcome,observed=excluded.observed,updated=CURRENT_TIMESTAMP',
        (run_id, revision, account['id'], outcome, observed),
    )


def save_item(db, account, data, content=None, *, storage_limit=0):
    experiment_id, run_id = data.get('experiment_id'), data.get('run_id')
    require_experiment(db, experiment_id, account, edit=True)
    if run_id is not None and require_run(db, run_id, account, edit=True)['experiment_id'] != experiment_id:
        raise sharing.AccessDenied
    kind = data.get('kind')
    if kind not in KINDS:
        raise ValueError('Choose an artifact type.')
    title = validate_text(data.get('title'), 'a title', 160, required=True)
    description = validate_text(data.get('description', ''), 'a description', 20000)
    filename = validate_text(data.get('filename', ''), 'a filename', 240)
    if filename and (filename in ('.', '..') or '/' in filename or '\\' in filename or any(ord(c) < 32 for c in filename)):
        raise ValueError('Use a simple filename.')
    external = validate_text(data.get('external_ref', ''), 'an external reference', 2048)
    if external and (content is not None or any(ord(c) < 32 for c in external)):
        raise ValueError('Choose an upload or an external reference.')
    if content is not None and (len(content) > MAX_FILE_BYTES or not filename):
        raise ValueError('Choose a file of up to 100 MiB.')
    audience = _audience(data.get('audience'))
    item_id = data.get('id')
    if item_id is None:
        item_id = db.execute('INSERT INTO research_items(experiment_id,run_id,owner_id,kind,title,audience) VALUES (?,?,?,?,?,?) RETURNING id',
                             (experiment_id, run_id, account['id'], kind, title, audience)).fetchone()[0]
    else:
        old = require_item(db, item_id, account, edit=True)
        if (old['experiment_id'], old['run_id'], old['kind']) != (experiment_id, run_id, kind):
            raise ValueError('An artifact cannot be moved or change type.')
        if data.get('revision') != old['revision']:
            raise sharing.EditConflict('This item changed. Reload it before saving.')
        if audience != old['audience'] and not sharing.is_owner(db, account, old['owner_id']):
            raise sharing.AccessDenied
        db.execute('UPDATE research_items SET title=?,audience=?,revision=revision+1 WHERE id=?', (title, audience, item_id))
    if storage_limit and content:
        from .library import require_upload_space
        require_upload_space(db, storage_limit, len(content))
    number = db.execute('SELECT COALESCE(MAX(number),0)+1 FROM research_versions WHERE item_id=?', (item_id,)).fetchone()[0]
    db.execute('INSERT INTO research_versions(item_id,number,creator_id,description,filename,external_ref,sha256,content) VALUES (?,?,?,?,?,?,?,?)',
               (item_id, number, account['id'], description, filename, external,
                hashlib.sha256(content).hexdigest() if content is not None else None, content))
    return item_id


def visible_experiments(db, account, document_id=None):
    if not account:
        return []
    grants = _read_grants(db, 'experiment', account)
    rows = db.execute(sharing.PAPER_SCOPE + f'''
        SELECT e.*, {sharing.owner_sql('e.owner_id')} AS owned,
               d.id AS visible_document, b.id AS goal_brief_id, git.head AS source_commit FROM experiments e
        LEFT JOIN visible_documents d ON d.id=e.research_document_id
        LEFT JOIN research_goal_briefs b ON b.experiment_id=e.id
        LEFT JOIN git_repository_state git ON git.kind='experiments' AND git.resource_id=e.id
        WHERE (:document IS NULL OR d.id=:document) ORDER BY e.id DESC
    ''', sharing.viewer_params(account, document=document_id))
    results = []
    for experiment, _ in _visible_rows(rows, account, grants, inherited=True):
        if experiment.pop('goal_brief_id') is not None:
            from . import goals
            try:
                goals.experiment_scope(db, account, experiment['id'])
            except sharing.AccessDenied:
                continue
        experiment['research_document_id'] = experiment.pop('visible_document')
        results.append(experiment)
    return results


def detail(db, account, experiment_id):
    experiment = require_experiment(db, experiment_id, account)
    can_edit = allowed(db, 'experiment', experiment, account, edit=True)
    experiment_data = dict(experiment)
    from . import projects
    linked = db.execute("SELECT project_id FROM project_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
    if linked:
        try:
            project = projects.scope(db, account, linked["project_id"])
        except sharing.AccessDenied:
            pass
        else:
            branch = f"experiment/{experiment_id}"
            experiment_data["project"] = {"id": project["id"], "title": project["title"], "branch": branch,
                                          "head": json.loads(project["refs"])[branch]}
    brief_id = experiment_data.pop('goal_brief_id')
    brief = None
    if brief_id is not None:
        brief = dict(db.execute("SELECT id,goal_id,stage,approach,conditions FROM research_goal_briefs WHERE id=?",
                               (brief_id,)).fetchone())
    document_id = experiment['research_document_id']
    if document_id is not None and not sharing.document_for(db, account, document_id):
        experiment_data['research_document_id'] = None
    if sharing.is_owner(db, account, experiment['owner_id']):
        _, names = _read_grants(db, 'experiment', account, experiment_id)
        experiment_data.update(names.get(experiment_id, {'readers': [], 'editors': []}))
    run_grants = _read_grants(db, 'run', account, experiment_id)
    viewer = sharing.viewer_params(account, experiment_id=experiment_id)
    run_rows = db.execute(
        f"SELECT *,{sharing.owner_sql('owner_id')} AS owned FROM experiment_runs WHERE experiment_id=:experiment_id ORDER BY id DESC",
        viewer,
    )
    runs = []
    for run, owned in _visible_rows(run_rows, account, run_grants):
        run['can_edit'] = can_edit and (owned or run_grants[0].get(run['id'], False))
        run['reproduction'] = json.loads(run['reproduction'])
        run['can_verify'] = can_verify_run(account, run, owned=owned)
        run['reproduction_checks'] = []
        if brief_id is not None:
            run['brief_id'] = brief_id
        runs.append(run)
    visible_runs = {run['id']: run for run in runs}
    run_ids = list(visible_runs)
    for start in range(0, len(run_ids), VERSION_BATCH_SIZE):
        batch = run_ids[start:start + VERSION_BATCH_SIZE]
        placeholders = ','.join('?' for _ in batch)
        for row in db.execute(
            'SELECT r.run_id,r.run_revision,a.username AS reviewer,r.outcome,r.observed,r.updated,'
            '(r.reviewer_id=?) AS mine FROM run_reproductions r JOIN accounts a ON a.id=r.reviewer_id '
            f'WHERE r.run_id IN ({placeholders}) ORDER BY r.run_revision DESC,r.updated DESC,r.reviewer_id',
            (account['id'], *batch),
        ):
            check = dict(row)
            check['mine'] = bool(check['mine'])
            visible_runs[check.pop('run_id')]['reproduction_checks'].append(check)
    item_grants = _read_grants(db, 'item', account, experiment_id)
    item_rows = db.execute(
        f"SELECT *,{sharing.owner_sql('owner_id')} AS owned FROM research_items WHERE experiment_id=:experiment_id ORDER BY id DESC",
        viewer,
    )
    items = {item['id']: dict(item, versions=[]) for item, _ in _visible_rows(
        (row for row in item_rows if row['run_id'] is None or row['run_id'] in visible_runs),
        account, item_grants,
    )}
    item_ids = list(items)
    for start in range(0, len(item_ids), VERSION_BATCH_SIZE):
        batch = item_ids[start:start + VERSION_BATCH_SIZE]
        placeholders = ','.join('?' for _ in batch)
        for row in db.execute(
            'SELECT item_id,id,number,creator_id,description,filename,external_ref,sha256,created, '
            f'length(content) AS size FROM research_versions WHERE item_id IN ({placeholders}) '
            'ORDER BY item_id,number DESC', batch,
        ):
            version = dict(row)
            items[version.pop('item_id')]['versions'].append(version)
    return {'experiment': experiment_data, 'runs': runs, 'items': list(items.values()),
            'can_edit': can_edit, 'brief': brief}


def version_content(db, account, version_id):
    row = db.execute('SELECT * FROM research_versions WHERE id=?', (version_id,)).fetchone()
    if not row:
        raise sharing.AccessDenied
    require_item(db, row['item_id'], account)
    if row['content'] is None:
        raise LookupError('This version has no uploaded file.')
    payload = bytes(row['content'])
    if hashlib.sha256(payload).hexdigest() != row['sha256']:
        raise ValueError('The stored file failed its integrity check.')
    return row['filename'], payload


def archive_version(db, account, version_id, path=None):
    """Browse an uploaded ZIP snapshot without extracting it to disk."""
    filename, payload = version_content(db, account, version_id)
    if not filename.lower().endswith(".zip"):
        raise LookupError("This version is not a ZIP archive.")
    footer = payload.rfind(b"PK\x05\x06", max(0, len(payload) - 65_557))
    if footer < 0 or footer + 22 > len(payload):
        raise ValueError("This ZIP archive is incomplete.")
    disk, directory_disk, disk_entries, entries, size, offset, comment_size = struct.unpack_from("<4H2IH", payload, footer + 4)
    if (disk or directory_disk or disk_entries != entries or entries > MAX_ARCHIVE_ENTRIES
            or size > MAX_ARCHIVE_DIRECTORY_BYTES or offset + size != footer or footer + 22 + comment_size != len(payload)):
        raise ValueError("Use a single ZIP archive of up to 5,000 entries with a standard directory.")
    try:
        with ZipFile(BytesIO(payload)) as bundle:
            files = {}
            for entry in bundle.infolist():
                name = entry.orig_filename
                if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                    continue
                if (len(name) > 1024 or "\\" in name or any(ord(char) < 32 for char in name)
                        or any(part in ("", ".", "..") for part in name.split("/")) or name in files):
                    raise ValueError("The ZIP contains an invalid or duplicate file path.")
                files[name] = entry
            if path is not None:
                entry = files.get(path)
                if entry is None or entry.file_size > MAX_FILE_BYTES:
                    raise LookupError("This archive file is unavailable.")
                if entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    raise ValueError("This file uses an unsupported ZIP compression method.")
                return path.rsplit("/", 1)[-1], bundle.read(entry)
            comment = bundle.comment.decode("ascii", errors="ignore").strip()
            commit = comment if re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", comment) else None
            return {"commit": commit, "files": [{"path": name, "size": entry.file_size}
                                                for name, entry in sorted(files.items())]}
    except (BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as error:
        raise ValueError("This ZIP archive cannot be read.") from error
