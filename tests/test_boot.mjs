import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { Blob } from 'node:buffer';

const files = ['api.js', 'metrics.js', 'library.js', 'documents.js', 'findings.js', 'goals.js', 'boot.js'];
const sources = files.map(name => fs.readFileSync(new URL(`../paper_app/web/${name}`, import.meta.url), 'utf8'));

for (const [path, expectedTitle] of [['/', 'Compare metrics'], ['/papers', 'Papers'], ['/documents', 'Markdown documents'], ['/account', 'Account']]) {
  const elements = new Map();
  function makeElement() {
    const fields = new Map();
    return {value: '', textContent: '', hidden: false, disabled: false, checked: false, options: [], validity: {valid: true},
      selectedOptions: [], dataset: {}, classList: {toggle() {}},
      elements: new Proxy({}, {get(_target, key) {if (!fields.has(key)) fields.set(key, makeElement()); return fields.get(key);}}),
      addEventListener() {}, setAttribute() {}, removeAttribute() {}, replaceChildren() {}, append() {}, reset() {}, closest() {return makeElement();},
      querySelectorAll() {return [];}, before() {}, setCustomValidity() {}};
  }
  const document = {title: '', getElementById(id) {if (!elements.has(id)) elements.set(id, makeElement()); return elements.get(id);},
    querySelectorAll() {return [];}, createElement() {return makeElement();}};
  const response = {account: null, papers: [], groups: [], memberships: [], metrics: [], comments: [],
    documents: [], archived_papers: [], document_targets: [], google_available: false,
    publishers: [], count: 0, total: 0, page: 1};
  const context = {document, location: {pathname: path, search: '', href: `http://127.0.0.1:8765${path}`}, URLSearchParams,
    localStorage: {getItem() {return null;}}, history: {replaceState() {}}, navigator: {},
    fetch: async () => ({ok: true, json: async () => response}),
    window: {addEventListener() {}}, addEventListener() {}, console, setTimeout, clearTimeout, Intl, URL, Blob};
  vm.createContext(context);
  for (let i = 0; i < files.length; i++) vm.runInContext(sources[i], context, {filename: files[i]});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(document.title, expectedTitle);
  const status = document.getElementById(path === '/account' ? 'account-status' : path === '/documents' ? 'document-status' : path === '/papers' ? 'library-status' : 'status');
  assert.equal(status.textContent, '', `Unexpected startup error on ${path}: ${status.textContent}`);
}
console.log('All page startup scripts passed');
