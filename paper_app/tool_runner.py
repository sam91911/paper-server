"""Run approved fixed-command jobs in rootless Podman containers."""
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import tarfile
from pathlib import Path
from threading import Thread

from . import experiments, library, tools_catalog

LOG_LIMIT = 1_000_000
TIMEOUT = 60


def _requester(db, job):
    row = db.execute(f"SELECT a.id,a.username,{experiments.accounts.ROLE_SQL.format(alias='a')} role FROM accounts a WHERE a.id=?", (job['requester_id'],)).fetchone()
    return dict(row) if row else None


def _validate(db, job):
    if hashlib.sha256(job['request_json'].encode()).hexdigest() != job['request_hash']:
        raise ValueError('Job request integrity check failed.')
    spec = json.loads(job['request_json'])
    account = _requester(db, job)
    run = experiments.require_run(db, job['run_id'], account, edit=True)
    tool = tools_catalog.require_tool(db, job['tool_id'], account)
    if (tool['revision'] != spec['tool_revision'] or tool['image_digest'] != spec['image']
        or json.loads(tool['command_json']) != spec['command']):
        raise ValueError('Tool configuration changed.')
    if not db.execute('SELECT 1 FROM tool_approvers WHERE account_id=?', (job['approver_id'],)).fetchone():
        raise ValueError('Approver is no longer authorized.')
    inputs = []
    for entry in spec['inputs']:
        version = db.execute('SELECT * FROM research_versions WHERE id=?', (entry['id'],)).fetchone()
        if not version or version['sha256'] != entry['sha256'] or version['content'] is None:
            raise ValueError('Input unavailable.')
        item = experiments.require_item(db, version['item_id'], account)
        payload = bytes(version['content'])
        if item['experiment_id'] != run['experiment_id'] or hashlib.sha256(payload).hexdigest() != version['sha256']:
            raise ValueError('Input integrity check failed.')
        inputs.append((version['id'], payload))
    return account, spec, inputs


def execute(database, job_id):
    with library.connect(database) as db:
        db.execute('BEGIN IMMEDIATE')
        job = db.execute('SELECT * FROM tool_jobs WHERE id=?', (job_id,)).fetchone()
        if not job or job['status'] != 'approved':
            return
        try:
            account, spec, inputs = _validate(db, job)
        except (ValueError, experiments.sharing.AccessDenied) as error:
            db.execute("UPDATE tool_jobs SET status='failed',log=?,updated=CURRENT_TIMESTAMP WHERE id=?", (str(error), job_id))
            return
        db.execute("UPDATE tool_jobs SET status='running',updated=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
    podman = shutil.which('podman')
    log = ''
    outputs = []
    try:
        if not podman:
            raise ValueError('Rootless Podman is unavailable.')
        check = subprocess.run([podman, 'info', '--format', '{{.Host.Security.Rootless}}'], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True)
        if check.stdout.strip().lower() != b'true':
            raise ValueError('Rootless Podman is required.')
        with tempfile.TemporaryDirectory(prefix='paper-job-') as temp:
            root = Path(temp)
            input_dir = root / 'inputs'
            input_dir.mkdir()
            for version_id, payload in inputs:
                (input_dir / str(version_id)).write_bytes(payload)
            name = f'paper-job-{job_id}-{os.urandom(8).hex()}'
            command = [podman, 'run', '--name', name, '--pull=never', '--network=none', '--read-only',
                       '--userns=keep-id', '--cap-drop=all', '--security-opt=no-new-privileges',
                       '--pids-limit=128', '--memory=512m', '--cpus=1', '--ulimit', 'fsize=104857600:104857600',
                       '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
                       '--tmpfs', '/outputs:rw,noexec,nosuid,size=104857600', '-v', f'{input_dir}:/inputs:ro',
                       spec['image'], *spec['command']]
            process = None
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                captured = bytearray()
                def drain():
                    while chunk := process.stdout.read(65536):
                        if len(captured) < LOG_LIMIT:
                            captured.extend(chunk[:LOG_LIMIT - len(captured)])
                reader = Thread(target=drain, daemon=True); reader.start()
                try:
                    code = process.wait(timeout=TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise ValueError('Tool timed out.')
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait()
                    reader.join(timeout=5)
                    log = captured.decode('utf-8', 'replace')
                if code:
                    raise ValueError(f'Tool failed with exit code {code}.')
                copy = subprocess.Popen([podman, 'cp', f'{name}:/outputs/.', '-'], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                archive = copy.stdout.read(experiments.MAX_FILE_BYTES + 2 * 1024 * 1024 + 1)
                if len(archive) > experiments.MAX_FILE_BYTES + 2 * 1024 * 1024:
                    copy.kill(); copy.wait()
                    raise ValueError('Tool output archive is too large.')
                if copy.wait(timeout=10):
                    raise ValueError('Could not collect tool output.')
                total = 0
                with tarfile.open(fileobj=io.BytesIO(archive), mode='r:*') as tar:
                    for member in tar:
                        if member.isdir() and member.name in ('.', './'):
                            continue
                        name_part = member.name.removeprefix('./')
                        if not member.isfile() or '/' in name_part or name_part in ('', '.', '..') or len(outputs) >= 20:
                            raise ValueError('Only up to 20 regular output files are permitted.')
                        total += member.size
                        if total > experiments.MAX_FILE_BYTES:
                            raise ValueError('Tool outputs exceed 100 MiB.')
                        outputs.append((name_part, tar.extractfile(member).read()))
            finally:
                subprocess.run([podman, 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
                if process and process.poll() is None:
                    process.kill(); process.wait()
        with library.connect(database) as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM tool_jobs WHERE id=?', (job_id,)).fetchone()
            account, _, _ = _validate(db, current)
            for filename, payload in outputs:
                experiments.save_item(db, account, {'experiment_id': current['experiment_id'], 'run_id': current['run_id'],
                    'kind': 'data', 'title': filename, 'filename': filename, 'description': f'Output of tool job {job_id}', 'audience': 'owner'}, payload)
            db.execute("UPDATE tool_jobs SET status='complete',log=?,updated=CURRENT_TIMESTAMP WHERE id=?", (log, job_id))
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError, experiments.sharing.AccessDenied) as error:
        with library.connect(database) as db:
            db.execute("UPDATE tool_jobs SET status='failed',log=?,updated=CURRENT_TIMESTAMP WHERE id=?", ((log + '\n' + str(error))[-LOG_LIMIT:], job_id))
