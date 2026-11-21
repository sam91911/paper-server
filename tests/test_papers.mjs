import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../paper_app/web/library.js', import.meta.url), 'utf8');
const code = source.slice(source.indexOf('function paperFilename('), source.indexOf('async function loadLibrary('));
const papers = Array.from({length: 205}, (_, i) => ({id: i + 1, path: `/p/paper-${i}.pdf`, title: `Title ${i}`,
  year: '2024', publisher: 'Publisher', authors: '', doi: '', venue: ''}));
const controls = new Map();
function element(id) {if (!controls.has(id)) controls.set(id, {}); return controls.get(id);}
let options = [];
const picker = {value: ''};
const context = {libraryData: {papers, memberships: []}, paperSearch: {value: ''}, paperGroupFilter: {value: ''},
  paperPublisherFilter: {value: ''}, paperYearFrom: {value: '', validity: {valid: true}},
  paperYearTo: {value: '', validity: {valid: true}}, paperPicker: picker, paperPage: 0, paperPageSize: 100,
  groupMembers: () => null, element, setOptions: (_picker, items) => {options = items;}};
vm.createContext(context);
vm.runInContext(code, context);
context.updatePaperOptions();
assert.equal(options.length, 100);
assert.equal(element('paper-page-status').textContent, 'Page 1 of 3');
context.paperPage = 2;
context.updatePaperOptions();
assert.equal(options.length, 5);
assert.equal(element('paper-page-next').disabled, true);
picker.value = '1';
context.updatePaperOptions();
assert.equal(options.length, 6);
assert.equal(options[0][0], 1);
context.paperSearch.value = 'paper-204';
context.updatePaperOptions();
assert.equal(element('paper-page-status').textContent, 'Page 1 of 1');
assert.equal(options.length, 2);
console.log('Paper list pagination passed');
