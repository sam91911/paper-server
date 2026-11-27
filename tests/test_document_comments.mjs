import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../paper_app/web/documents.js', import.meta.url), 'utf8');
const library = fs.readFileSync(new URL('../paper_app/web/library.js', import.meta.url), 'utf8');
const helpers = library.slice(library.indexOf('function requestedComment('), library.indexOf('async function loadPaperComments()'));
const start = source.indexOf('async function loadDocumentComments()');
const code = source.slice(start, source.indexOf('element("cancel-document-reply").addEventListener', start));
const controls = new Map();
function element(id) {
  if (!controls.has(id)) controls.set(id, {hidden: false, disabled: false, addEventListener(type, callback) {this[type] = callback;}});
  return controls.get(id);
}
let selected = {id: 1};
const pending = [];
const rendered = [];
const data = {comments: []};
const context = {location: {search: ""}, URLSearchParams, libraryData: data, documentCommentSequence: 0, nextDocumentCommentBefore: null,
  element, selectedDocument: () => selected,
  api: route => new Promise(resolve => pending.push({route, resolve})),
  renderDocumentComments: item => rendered.push(item?.id), documentStatus: {textContent: ''}};
vm.createContext(context);
vm.runInContext(helpers + code, context);
const first = context.loadDocumentComments();
selected = {id: 2};
const second = context.loadDocumentComments();
pending[1].resolve({comments: [{id: 20}], next_before: 20});
await second;
pending[0].resolve({comments: [{id: 10}], next_before: null});
await first;
assert.deepEqual(data.comments, [{id: 20}]);
const button = element('older-document-comments');
assert.equal(button.hidden, false);
const older = button.click({currentTarget: button});
assert.equal(pending[2].route, 'document-comments?document_id=2&before=20');
pending[2].resolve({comments: [{id: 15}], next_before: null});
await older;
assert.deepEqual(Array.from(data.comments, item => item.id), [15, 20]);
assert.equal(button.hidden, true);
assert.equal(button.disabled, false);
assert.deepEqual(rendered, [2, 2]);
console.log('Document comment pagination passed');
