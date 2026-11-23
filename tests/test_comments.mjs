import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../paper_app/web/library.js', import.meta.url), 'utf8');
const code = source.slice(source.indexOf('async function loadPaperComments()'), source.indexOf('async function updateLibrary('));
const controls = new Map();
function element(id) {
  if (!controls.has(id)) controls.set(id, {hidden: false, disabled: false, addEventListener(type, callback) {this[type] = callback;}});
  return controls.get(id);
}
let selected = {id: 1};
let pending = [];
let renders = [];
const data = {comments: [], account: {id: 1}};
const commentForm = {hidden: false};
const context = {libraryData: data, commentLoadSequence: 0, nextCommentBefore: null,
  element, selectedPaper: () => selected, commentForm, commentDrafts: new Map(),
  api: route => new Promise(resolve => pending.push({route, resolve})),
  showReplyTarget() {}, renderPaperComments: item => renders.push(item.id),
  libraryStatus: {textContent: ''}};
vm.createContext(context);
vm.runInContext(code, context);
const first = context.loadPaperComments();
assert.equal(commentForm.hidden, true);
assert.equal(controls.get('paper-comments-status').textContent, 'Loading comments…');
assert.equal(pending[0].route, 'paper-comments?paper_id=1');
// A slower request for the previous selection must not replace the new result.
selected = {id: 2};
const second = context.loadPaperComments();
pending[1].resolve({comments: [{id: 20}], next_before: 20});
await second;
pending[0].resolve({comments: [{id: 10}], next_before: null});
await first;
assert.deepEqual(data.comments, [{id: 20}]);
assert.equal(controls.get('older-comments').hidden, false);
assert.equal(commentForm.hidden, false);
const button = controls.get('older-comments');
const older = button.click({currentTarget: button});
assert.equal(button.disabled, true);
assert.equal(pending[2].route, 'paper-comments?paper_id=2&before=20');
pending[2].resolve({comments: [{id: 15}], next_before: null});
await older;
assert.deepEqual(Array.from(data.comments, item => item.id), [15, 20]);
assert.equal(button.hidden, true);
assert.equal(button.disabled, false);
assert.deepEqual(renders, [2, 2]);
console.log('Comment loading and pagination passed');
