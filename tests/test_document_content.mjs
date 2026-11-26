import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../paper_app/web/documents.js', import.meta.url), 'utf8');
const code = source.slice(source.indexOf('async function ensureSelectedDocument()'), source.indexOf('async function openRequestedDocument()'));
let selected = {id: 1, title: 'One'};
const data = {documents: [selected]};
const pending = [];
const context = {libraryData: data, documentLoadSequence: 0, selectedDocument: () => selected,
  api: route => new Promise(resolve => pending.push({route, resolve}))};
vm.createContext(context);
vm.runInContext(code, context);
const first = context.ensureSelectedDocument();
assert.equal(pending[0].route, 'document?id=1');
selected = {id: 2, title: 'Two'};
data.documents.push(selected);
const second = context.ensureSelectedDocument();
pending[1].resolve({document: {id: 2, markdown: 'content two', revision: 2}});
assert.equal((await second).markdown, 'content two');
pending[0].resolve({document: {id: 1, markdown: 'stale'}});
assert.equal(await first, undefined);
assert.equal(data.documents[0].markdown, undefined);
assert.equal((await context.ensureSelectedDocument()).markdown, 'content two');
assert.equal(pending.length, 2);
selected = undefined;
assert.equal(await context.ensureSelectedDocument(), null);
console.log('Document content loading passed');

const openCode = source.slice(source.indexOf('function canEditDocument('), source.indexOf('async function showDocuments('));
for (const kind of ['document', 'news', 'discussion']) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {classList: {toggle() {}}});
    return elements.get(id);
  }
  const fields = Object.fromEntries(['topic', 'source_url', 'scheduled_at', 'title', 'markdown', 'audience', 'recipients']
    .map(name => [name, {value: ''}]));
  const editor = {elements: fields, reset() {}};
  const sandbox = vm.createContext({
    element, documentEditor: editor, documentStatus: {}, documentCommentForm: {reset() {}},
    libraryData: {account: {id: 1}}, activeDocumentTopic: '', audienceLabels: {}, roleLabels: {},
    newsWorkspace: kind === 'news', discussionWorkspace: kind === 'discussion', feedWorkspace: kind !== 'document',
    setDocumentReply() {}, renderDocumentComments() {}, closePdf() {}, renderDocumentContext() {},
    loadDocumentGoalOptions() {}, renderDiscussionMeta() {}, renderDocumentFeed() {}, selectAudience() {},
    renderMarkdown() {}, localSchedule() {},
  });
  vm.runInContext(openCode, sandbox);
  const owned = {id: 3, owner_id: 1, title: 'Stored title', markdown: 'Stored content', revision: 2,
    ...(kind === 'news' ? {source_url: 'https://example.com/article'} : {})};
  sandbox.openDocument(owned);
  assert.equal(editor.hidden, true, kind);
  assert.equal(element('edit-document').hidden, false, kind);
  assert.equal(element('preview-title').textContent, owned.title, kind);
  sandbox.openDocument(owned, {edit: true});
  assert.equal(editor.hidden, false, kind);
  fields.markdown.value = 'Unsaved draft';
  sandbox.openDocument(owned);
  assert.equal(editor.hidden, true, kind);
  assert.equal(fields.markdown.value, owned.markdown, kind);
  sandbox.openDocument({...owned, owner_id: 2}, {edit: true});
  assert.equal(editor.hidden, true, kind);
  assert.equal(element('edit-document').hidden, true, kind);
}
