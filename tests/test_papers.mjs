import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../paper_app/web/library.js', import.meta.url), 'utf8');
const papers = Array.from({length: 105}, (_, index) => ({
  id: index + 1, path: `paper-${index + 1}.pdf`, title: `Paper ${index + 1}`,
  ...[
    {source_url: 'https://publisher.example/paper', doi: '10.1234/with-link'},
    {doi: '10.1234/doi#suffix'},
    {source_url: 'javascript:alert(1)'},
  ][index],
}));

function makeElement(tag) {
  const listeners = new Map();
  const fields = new Map();
  return {
    tag, value: '', textContent: '', hidden: false, disabled: false, children: [],
    dataset: {}, validity: {valid: true}, open: false,
    get options() {return this.children.filter(child => child.tag === 'option');},
    get selectedOptions() {return this.options.filter(option => option.value === this.value);},
    elements: new Proxy({}, {
      get(_target, field) {
        if (!fields.has(field)) fields.set(field, makeElement());
        return fields.get(field);
      },
    }),
    addEventListener(event, action) {listeners.set(event, action);},
    fire(event) {return listeners.get(event)({currentTarget: this, preventDefault() {}});},
    replaceChildren() {this.children = []; this.value = '';},
    querySelectorAll() {return [];},
    closest() {return this;},
    reset() {},
    setAttribute(name, value) {this[name] = value;},
    removeAttribute(name) {delete this[name];},
    getAttribute(name) {return this[name];},
    setCustomValidity(message) {this.validationMessage = message;},
    scrollIntoView() {},
    focus() {this.focused = true;},
  };
}

function responsePage(page = 1, matches = papers) {
  return {page, count: matches.length, total: papers.length, papers: matches.slice((page - 1) * 100, page * 100)};
}

function setup(search = '') {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, makeElement());
    return elements.get(id);
  }
  const calls = [];
  const pending = new Map();
  function next(route) {
    let resolve, reject;
    const promise = new Promise((ok, fail) => {resolve = ok; reject = fail;});
    pending.set(route, promise);
    return {resolve, reject};
  }
  async function api(route) {
    calls.push(route);
    if (pending.has(route)) {
      const result = pending.get(route);
      pending.delete(route);
      return result;
    }
    const url = new URL(route, 'http://127.0.0.1:8765/api/');
    const params = url.searchParams;
    if (url.pathname === '/api/paper-catalog') {
      const result = responsePage(Number(params.get('page')));
      if (params.has('facets')) Object.assign(result, {
        account: {id: 1, role: 'user'}, groups: [{id: 1, name: 'Example'}], publishers: ['Example'],
      });
      return result;
    }
    if (url.pathname === '/api/paper-detail') {
      const id = Number(params.get('paper_id'));
      return {paper: {...papers[id - 1], owner_id: 1, audience: 'owner', has_pdf: id === 105}, group_ids: [1]};
    }
    if (url.pathname === '/api/paper-comments') return {comments: [], next_before: null};
    if (url.pathname === '/api/paper-comment-targets') return {
      papers: [papers[104]], documents: [{id: 5, title: 'Notes'}],
    };
    if (url.pathname === '/api/paper-archive') return {papers: []};
    throw new Error(`Unexpected request: ${route}`);
  }

  const location = new URL(`http://127.0.0.1:8765/papers${search}`);
  let timer;
  const context = vm.createContext({
    element, location, URL, URLSearchParams, api,
    document: {querySelectorAll: () => []},
    add(parent, tag, text) {
      const child = makeElement(tag);
      child.textContent = text ?? '';
      parent.children.push(child);
      return child;
    },
    paperPDFURL: id => `/papers/${id}/source.pdf`,
    history: {replaceState(_state, _title, url) {location.href = url;}},
    addEventListener() {},
    setTimeout(callback, delay) {assert.equal(delay, 250); timer = callback;},
    clearTimeout() {timer = null;},
  });
  vm.runInContext(source, context);
  const picker = element('library-paper');
  return {
    element, picker, calls, next, location,
    load: () => vm.runInContext('loadLibrary()', context),
    select(id) {
      picker.value = id == null ? '' : String(id);
      return picker.fire('change');
    },
    search(value) {
      const field = element('paper-search');
      field.value = value;
      field.fire('input');
    },
    flushSearch() {return timer();},
  };
}

test('catalog starts bounded, preserves selection across pages and ignores stale searches', async () => {
  const {element, picker, load, select, calls, search, flushSearch, next} = setup();
  await load();
  assert.deepEqual(calls, ['paper-catalog?page=1&facets=1']);
  assert.equal(element('paper-browse-controls').open, true);
  assert.equal(picker.options.length, 101);
  const first = element('paper-catalog-list').children[0].children[0];
  assert.equal(first.href, '/papers?paper=1');
  await first.fire('click');
  assert.equal(element('paper-detail-title').textContent, 'Paper 1');
  assert.equal(element('paper-detail-title').focused, true);
  assert.equal(element('paper-browse-controls').open, false);
  assert.equal(element('paper-catalog-list').children[0].children[0]['aria-current'], 'true');
  await element('paper-page-next').fire('click');
  assert.equal(element('paper-page-status').textContent, 'Page 2 of 2');
  assert.equal(picker.value, '1');
  assert.equal(picker.options[1].textContent, 'Paper 1 (selected)');

  const earlier = next('paper-catalog?page=1&q=old');
  search('old');
  const staleSearch = flushSearch();
  const later = next('paper-catalog?page=1&q=new');
  search('new');
  earlier.resolve(responsePage(1, [papers[2]]));
  await staleSearch;
  assert.equal(element('paper-search-status').textContent, 'Loading papers…');
  const currentSearch = flushSearch();
  later.resolve(responsePage(1, [papers[3]]));
  await currentSearch;
  assert.deepEqual(picker.options.map(option => option.value), ['', '1', '4']);
  assert.equal(element('paper-search-status').textContent, '1 of 105 papers match.');

  const year = element('paper-year-from');
  year.value = '990';
  year.validity.valid = false;
  const reads = calls.length;
  await year.fire('input');
  assert.equal(calls.length, reads);
  assert.equal(element('paper-search-status').textContent, 'Enter a valid publication year range.');
  assert.equal(picker.value, '1');
});

test('deep links open PDF pages and stale detail failures preserve the latest selection', async () => {
  const {element, picker, load, next, select, location} = setup('?paper=105&page=3');
  await load();
  assert.equal(picker.value, '105');
  assert.equal(element('paper-pdf-frame').src, '/papers/105/source.pdf#page=3');

  const old = next('paper-detail?paper_id=1');
  const oldSelection = select(1);
  await select(2);
  old.reject(new Error('Old request failed'));
  await oldSelection;
  assert.equal(location.search, '?paper=2');
  assert.equal(element('paper-detail-status').textContent, '');
  assert.equal(element('paper-detail').hidden, false);

  const unavailable = next('paper-detail?paper_id=1');
  const loading = select(1);
  unavailable.reject(new Error('Temporary failure'));
  await loading;
  assert.equal(location.search, '?paper=1');
  assert.equal(element('paper-detail-retry').hidden, false);
  assert.equal(element('paper-detail').hidden, true);
  await element('paper-detail-retry').fire('click');
  assert.equal(element('paper-detail').hidden, false);

  const hidden = next('paper-detail?paper_id=2');
  const blocked = select(2);
  hidden.reject(Object.assign(new Error('Unavailable'), {status: 404}));
  await blocked;
  assert.equal(location.search, '');
  assert.equal(picker.value, '');
  assert.equal(element('paper-detail').hidden, true);
});

test('lazy archive and comment targets preserve a draft across selection and refresh', async () => {
  const {element, load, select, calls} = setup();
  await load();
  await select(1);
  assert.equal(calls.includes('paper-comment-targets'), false);
  assert.equal(calls.includes('paper-archive'), false);
  const comments = element('paper-comments');
  comments.open = true;
  await comments.fire('toggle');
  const form = element('add-comment');
  form.elements.target.value = 'document:5';
  form.elements.position.value = '2';
  element('new-comment').value = 'Draft';
  form.fire('input');

  await select(2);
  await select(1);
  assert.equal(form.elements.target.value, 'document:5');
  assert.equal(form.elements.position.value, '2');
  assert.equal(element('new-comment').value, 'Draft');
  assert.equal(calls.filter(route => route === 'paper-comment-targets').length, 1);
  const archive = element('paper-archive');
  archive.open = true;
  await archive.fire('toggle');
  assert.equal(calls.filter(route => route === 'paper-archive').length, 1);
  await load();
  assert.equal(calls.filter(route => route === 'paper-comment-targets').length, 2);
  assert.equal(calls.filter(route => route === 'paper-archive').length, 2);
  assert.equal(form.elements.target.value, 'document:5');
});

test('paper detail links to a publication even when the library has no PDF', async () => {
  const {element, load, select} = setup();
  await load();
  const link = element('paper-web-source');
  await select(1);
  assert.equal(link.hidden, false);
  assert.equal(link.href, 'https://publisher.example/paper');
  assert.equal(element('paper-file-links').hidden, true);
  await select(2);
  assert.equal(link.href, 'https://doi.org/10.1234/doi%23suffix');
  await select(3);
  assert.equal(link.hidden, true);
  assert.equal(link.href, undefined);
});

test('paper metadata editing opens on request and closes when switching papers', async () => {
  const {element, load, select} = setup();
  await load();
  await select(1);
  assert.equal(element('edit-paper').hidden, false);
  assert.equal(element('paper-metadata-editor').hidden, true);
  element('edit-paper').fire('click');
  assert.equal(element('paper-metadata-editor').hidden, false);
  assert.equal(element('metadata').elements.title.value, 'Paper 1');
  element('metadata').elements.title.value = 'Unsaved change';
  element('cancel-paper-edit').fire('click');
  assert.equal(element('paper-metadata-editor').hidden, true);
  element('edit-paper').fire('click');
  assert.equal(element('metadata').elements.title.value, 'Paper 1');
  await select(2);
  assert.equal(element('paper-metadata-editor').hidden, true);
});
