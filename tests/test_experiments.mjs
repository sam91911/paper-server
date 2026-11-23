import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../paper_app/web/experiments.js', import.meta.url), 'utf8');

function element() {
  const listeners = new Map();
  return {
    value: '',
    textContent: '',
    hidden: false,
    disabled: false,
    children: [],
    append(child) { this.children.push(child); },
    replaceChildren() { this.children = []; this.value = ''; },
    addEventListener(type, listener) { listeners.set(type, listener); },
    fire(type) { return listeners.get(type)({preventDefault() {}}); },
  };
}

function result(id) {
  return {
    experiment: {id, title: `Experiment ${id}`, revision: 1, description: ''},
    runs: [{id: id * 10, title: `Run ${id}`, status: 'planned'}],
    items: [],
  };
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
  return {promise, resolve, reject};
}

async function setup(search = '') {
  const elements = new Map();
  function get(id) {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  }
  for (const id of ['experiment-form', 'run-form', 'item-form', 'grant-form', 'experiment-workspace-form']) {
    const form = get(id);
    const button = element();
    const fields = new Map();
    if (id === 'item-form') fields.set('run_id', get('run-select'));
    form.elements = new Proxy({}, {
      get(_target, key) {
        if (!fields.has(key)) fields.set(key, {value: '', files: []});
        return fields.get(key);
      },
    });
    form.querySelector = () => button;
    form.reset = () => {
      for (const field of fields.values()) {
        field.value = '';
        if (field.files) field.files = [];
      }
    };
  }
  const queued = new Map();
  const calls = [];
  function next(route) {
    const request = deferred();
    if (!queued.has(route)) queued.set(route, []);
    queued.get(route).push(request);
    return request;
  }
  async function api(route, data) {
    calls.push({route, data});
    const request = queued.get(route)?.shift();
    if (request) return request.promise;
    if (route === 'experiments' && data === undefined) {
      return {experiments: [result(1).experiment, result(2).experiment]};
    }
    if (route === 'research-tools') return {tools: [], host_tools: []};
    throw new Error(`Unexpected request ${route}`);
  }
  const document = {getElementById: get, createElement: element, querySelectorAll: () => []};
  async function fetch(route, options) {
    calls.push({route, options});
    return {ok: true, json: async () => ({id: 4})};
  }
  vm.runInNewContext(source, {document, api, fetch, location: {search}, URLSearchParams});
  await new Promise(resolve => setImmediate(resolve));
  const picker = get('experiments');
  function select(id) {
    assert.equal(picker.disabled, false);
    picker.value = id === null ? '' : String(id);
    return picker.fire('change');
  }
  return {get, calls, next, picker, select};
}

test('a research document link opens and prefills the new experiment form', async () => {
  const {get} = await setup('?document=7');
  assert.equal(get('new-experiment').open, true);
  assert.equal(get('experiment-form').elements.research_document_id.value, '7');
});

for (const staleError of [false, true]) {
  test(`latest selection wins when the older request ${staleError ? 'fails' : 'succeeds'}`, async () => {
    const {get, calls, next, select} = await setup();
    const previous = next('experiment-detail?id=1');
    const loaded = select(1);
    previous.resolve(result(1));
    await loaded;
    const itemForm = get('item-form');
    itemForm.elements.title.value = 'Draft from experiment 1';
    itemForm.elements.run_id.value = '10';
    itemForm.elements.file.files = [{name: 'previous.txt'}];

    const loading = next('experiment-detail?id=2');
    const pending = select(2);
    assert.equal(get('detail').hidden, true);
    assert.equal(itemForm.querySelector('button').disabled, true);
    assert.equal(itemForm.elements.title.value, '');
    assert.equal(itemForm.elements.run_id.value, '');
    assert.equal(itemForm.elements.file.files.length, 0);
    await itemForm.fire('submit');
    assert.equal(calls.some(call => call.route === 'research-items'), false);

    const stale = next('experiment-detail?id=1');
    const staleSelection = select(1);
    const current = next('experiment-detail?id=2');
    const currentSelection = select(2);
    current.resolve(result(2));
    await currentSelection;
    if (staleError) stale.reject(new Error('Older request failed'));
    else stale.resolve(result(1));
    const earlierMatch = result(2);
    earlierMatch.experiment.title = 'Older result for experiment 2';
    loading.resolve(earlierMatch);
    await Promise.all([staleSelection, pending]);

    assert.match(get('experiment-title').textContent, /^Experiment 2 /);
    assert.equal(get('run-select').children[1].value, 20);
    assert.equal(get('status').textContent, '');
    assert.equal(get('detail').hidden, false);

    const refreshed = next('experiment-detail?id=2');
    itemForm.elements.run_id.value = '20';
    itemForm.elements.file.files = [{name: 'upload.txt'}];
    const save = itemForm.fire('submit');
    const upload = calls.find(call => call.route === '/api/research-upload');
    const metadata = JSON.parse(decodeURIComponent(upload.options.headers['X-Research-Metadata']));
    assert.equal(metadata.experiment_id, 2);
    assert.equal(metadata.run_id, 20);
    refreshed.resolve(result(2));
    await save;
  });
}

test('clearing the selection and failed loads keep the detail hidden', async () => {
  const {get, next, select} = await setup();
  const pending = next('experiment-detail?id=1');
  const selecting = select(1);
  await select(null);
  pending.resolve(result(1));
  await selecting;
  assert.equal(get('detail').hidden, true);
  assert.equal(get('status').textContent, '');

  const failed = next('experiment-detail?id=2');
  const loading = select(2);
  failed.reject(new Error('Unavailable'));
  await loading;
  assert.equal(get('detail').hidden, true);
  assert.equal(get('run-form').querySelector('button').disabled, true);
  assert.match(get('status').textContent, /Unavailable/);
  assert.equal(get('retry-experiment-load').hidden, false);
});

test('failed saves retain input and successful saves can retry only the reload', async () => {
  const {get, calls, next, picker, select} = await setup();
  const initial = next('experiment-detail?id=2');
  const selecting = select(2);
  initial.resolve(result(2));
  await selecting;

  const form = get('run-form');
  form.elements.title.value = 'My run';
  const failed = next('experiment-runs');
  const saving = form.fire('submit');
  assert.equal(picker.disabled, true);
  assert.equal(form.querySelector('button').disabled, true);
  await form.fire('submit');
  failed.reject(new Error('Could not save'));
  await saving;
  assert.equal(form.elements.title.value, 'My run');
  assert.equal(get('status').textContent, 'Could not save');
  assert.equal(picker.disabled, false);

  const successful = next('experiment-runs');
  const failedReload = next('experiment-detail?id=2');
  const retrySave = form.fire('submit');
  successful.resolve({id: 5});
  failedReload.reject(new Error('Could not connect'));
  await retrySave;
  assert.equal(form.elements.title.value, '');
  assert.equal(get('detail').hidden, true);
  assert.match(get('status').textContent, /^Saved\. Could not load experiment/);

  const successfulReload = next('experiment-detail?id=2');
  const retry = get('retry-experiment-load').fire('click');
  successfulReload.resolve(result(2));
  await retry;
  assert.equal(get('detail').hidden, false);
  assert.equal(get('status').textContent, 'Saved.');
  const writes = calls.filter(call => call.route === 'experiment-runs');
  assert.equal(writes.length, 2);
  assert.ok(writes.every(call => call.data.experiment_id === 2 && call.data.title === 'My run'));
});
