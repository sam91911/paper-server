"""HTTP operations for experiments and their versioned artifacts."""
from . import experiments, sharing, tools_catalog


def update(handler, db, data):
    account = handler.require_account(db)
    if handler.path == '/api/experiments':
        return {'id': experiments.save_experiment(db, account, data)}
    if handler.path == '/api/experiment-runs':
        return {'id': experiments.save_run(db, account, data)}
    if handler.path == '/api/run-reproductions':
        experiments.verify_run(db, account, data)
        return {}
    if handler.path == '/api/research-items':
        return {'id': experiments.save_item(db, account, data)}
    if handler.path == '/api/tool-jobs':
        return {'id': tools_catalog.create_job(db, account, data)}
    if handler.path == '/api/approve-tool-job':
        account = handler.require_browser_account(db)
        job_id = data.get('id')
        if type(job_id) is not int:
            raise ValueError('Choose a job.')
        tools_catalog.approve_job(db, account, job_id)
        return {}
    if handler.path == '/api/research-grants':
        kind, item_id = data.get('kind'), data.get('id')
        require = {'experiment': experiments.require_experiment, 'run': experiments.require_run,
                   'item': experiments.require_item, 'tool': tools_catalog.require_tool}.get(kind)
        if not require or type(item_id) is not int:
            raise ValueError('Choose an item.')
        row = require(db, item_id, account) if kind == 'tool' else require(db, item_id, account, edit=True)
        experiments.set_grants(db, kind, item_id, account, row, data.get('readers', []), data.get('editors', []))
        return {}
    raise LookupError
