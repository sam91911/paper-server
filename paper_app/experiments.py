"""Experiments, runs and immutable, access-controlled research artifacts."""
import hashlib
import json
import re
from urllib.parse import urlsplit

from . import accounts, sharing

MAX_FILE_BYTES = 100 * 1024 * 1024
KINDS = ('code', 'environment', 'equipment', 'tool_record', 'data')
VERSION_BATCH_SIZE = 500
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
    if row['owner_id'] == account['id']:
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
        SELECT e.*, b.id AS goal_brief_id FROM experiments e
        LEFT JOIN research_goal_briefs b ON b.experiment_id=e.id WHERE e.id=?
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
    if row['owner_id'] != actor['id']:
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
        'SELECT g.item_id,g.account_id,g.can_edit,r.owner_id,a.username '
        f'FROM research_grants g JOIN {table} r ON r.id=g.item_id '
        'JOIN accounts a ON a.id=g.account_id '
        'WHERE g.kind=:kind AND (r.owner_id=:viewer OR g.account_id=:viewer)'
        + scope + ' ORDER BY a.username',
        {'kind': kind, 'viewer': account['id'], 'experiment_id': experiment_id},
    )
    direct = {}
    names = {}
    for row in rows:
        item_id = row['item_id']
        if row['account_id'] == account['id']:
            direct[item_id] = bool(row['can_edit'])
        if row['owner_id'] == account['id']:
            groups = names.setdefault(item_id, {'readers': [], 'editors': []})
            groups['editors' if row['can_edit'] else 'readers'].append(row['username'])
    return direct, names


def _visible_rows(rows, account, grants, *, inherited=False):
    direct, names = grants
    for row in rows:
        if row['owner_id'] == account['id']:
            yield dict(row, **names.get(row['id'], {'readers': [], 'editors': []}))
        elif (row['id'] in direct or _audience_allows(row['audience'], account['role'])
              or (inherited and row['goal_brief_id'] is not None)):
            yield dict(row)


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
        if not sharing.document_for(db, account, document_id):
            raise sharing.AccessDenied
    if item_id is None:
        item_id = db.execute(
            'INSERT INTO experiments(owner_id,title,description,paper_id,audience,research_document_id) VALUES (?,?,?,?,?,?)',
            (account['id'], title, description, paper_id, audience, document_id),
        ).lastrowid
    else:
        if data.get('revision') != row['revision']:
            raise sharing.EditConflict('This experiment changed. Reload it before saving.')
        if audience != row['audience'] and account['id'] != row['owner_id']:
            raise sharing.AccessDenied
        db.execute('UPDATE experiments SET title=?,description=?,paper_id=?,audience=?,research_document_id=?,'
                   'revision=revision+1,updated=CURRENT_TIMESTAMP WHERE id=?',
                   (title, description, paper_id, audience, document_id, item_id))
    return item_id


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
    if run_id is None:
        return db.execute(
            'INSERT INTO experiment_runs(experiment_id,owner_id,title,description,status,audience,methods,settings)'
            ' VALUES (?,?,?,?,?,?,?,?)',
            (experiment_id, account['id'], title, description, status, audience, methods, settings),
        ).lastrowid
    if row['experiment_id'] != experiment_id:
        raise sharing.AccessDenied
    if data.get('revision') != row['revision']:
        raise sharing.EditConflict('This run changed. Reload it before saving.')
    if audience != row['audience'] and account['id'] != row['owner_id']:
        raise sharing.AccessDenied
    db.execute('UPDATE experiment_runs SET title=?,description=?,status=?,audience=?,methods=?,settings=?,'
               'revision=revision+1,updated=CURRENT_TIMESTAMP WHERE id=?',
               (title, description, status, audience, methods, settings, run_id))
    return run_id


def save_item(db, account, data, content=None):
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
        item_id = db.execute('INSERT INTO research_items(experiment_id,run_id,owner_id,kind,title,audience) VALUES (?,?,?,?,?,?)',
                             (experiment_id, run_id, account['id'], kind, title, audience)).lastrowid
    else:
        old = require_item(db, item_id, account, edit=True)
        if (old['experiment_id'], old['run_id'], old['kind']) != (experiment_id, run_id, kind):
            raise ValueError('An artifact cannot be moved or change type.')
        if data.get('revision') != old['revision']:
            raise sharing.EditConflict('This item changed. Reload it before saving.')
        if audience != old['audience'] and account['id'] != old['owner_id']:
            raise sharing.AccessDenied
        db.execute('UPDATE research_items SET title=?,audience=?,revision=revision+1 WHERE id=?', (title, audience, item_id))
    number = db.execute('SELECT COALESCE(MAX(number),0)+1 FROM research_versions WHERE item_id=?', (item_id,)).fetchone()[0]
    db.execute('INSERT INTO research_versions(item_id,number,creator_id,description,filename,external_ref,sha256,content) VALUES (?,?,?,?,?,?,?,?)',
               (item_id, number, account['id'], description, filename, external,
                hashlib.sha256(content).hexdigest() if content is not None else None, content))
    return item_id


def visible_experiments(db, account, document_id=None):
    if not account:
        return []
    grants = _read_grants(db, 'experiment', account)
    rows = db.execute(sharing.PAPER_SCOPE + '''
        SELECT e.*, d.id AS visible_document, b.id AS goal_brief_id FROM experiments e
        LEFT JOIN visible_documents d ON d.id=e.research_document_id
        LEFT JOIN research_goal_briefs b ON b.experiment_id=e.id
        WHERE (:document IS NULL OR d.id=:document) ORDER BY e.id DESC
    ''', sharing.viewer_params(account, document=document_id))
    results = []
    for experiment in _visible_rows(rows, account, grants, inherited=True):
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
    brief_id = experiment_data.pop('goal_brief_id')
    brief = None
    if brief_id is not None:
        brief = dict(db.execute("SELECT id,goal_id,stage,approach,conditions FROM research_goal_briefs WHERE id=?",
                               (brief_id,)).fetchone())
    document_id = experiment['research_document_id']
    if document_id is not None and not sharing.document_for(db, account, document_id):
        experiment_data['research_document_id'] = None
    if experiment['owner_id'] == account['id']:
        _, names = _read_grants(db, 'experiment', account, experiment_id)
        experiment_data.update(names.get(experiment_id, {'readers': [], 'editors': []}))
    run_grants = _read_grants(db, 'run', account, experiment_id)
    run_rows = db.execute('SELECT * FROM experiment_runs WHERE experiment_id=? ORDER BY id DESC', (experiment_id,))
    runs = list(_visible_rows(run_rows, account, run_grants))
    for run in runs:
        run['can_edit'] = can_edit and (run['owner_id'] == account['id'] or run_grants[0].get(run['id'], False))
        if brief_id is not None:
            run['brief_id'] = brief_id
    visible_run_ids = {run['id'] for run in runs}
    item_grants = _read_grants(db, 'item', account, experiment_id)
    item_rows = db.execute('SELECT * FROM research_items WHERE experiment_id=? ORDER BY id DESC', (experiment_id,))
    items = {item['id']: dict(item, versions=[]) for item in _visible_rows(
        (row for row in item_rows if row['run_id'] is None or row['run_id'] in visible_run_ids),
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
