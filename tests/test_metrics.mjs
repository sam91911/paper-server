import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the real rendering function with a small DOM stand-in so page bounds,
// filtering, sorting and chart scale are tested without a browser installation.
const source = fs.readFileSync(new URL('../paper_app/web/metrics.js', import.meta.url), 'utf8');
const renderCode = source.slice(source.indexOf('function render() {'), source.indexOf('element("results-previous").addEventListener'));
const elements = new Map();
function makeElement() {
  return {children: [], textContent: '', disabled: false, style: {},
    replaceChildren() { this.children = []; }, setAttribute() {}};
}
function element(id) { if (!elements.has(id)) elements.set(id, makeElement()); return elements.get(id); }
function add(parent, tag, text) { const child = makeElement(); child.tag = tag; child.textContent = text ?? ''; parent.children.push(child); return child; }
const rows = Array.from({length: 205}, (_, i) => ({paper_id: i + 1, paper: `paper-${i}.pdf`, page: 1,
  conditions: '', group: 'power', number: i, value: `${i}`, unit: 'W', originalValue: `${i}`, originalUnit: 'W'}));
let pairRenders = 0;
const context = {element, add, metrics: rows, paper: {value: ''}, conditions: {value: ''},
  group: {value: 'power', selectedOptions: [{textContent: 'Power'}]}, sort: {value: 'asc'},
  status: element('status'), libraryGroupMembers: null, resultPageSize: 100, resultPage: 0,
  comparisonPanel: {open: true},
  renderPairs() {pairRenders++;}, addPaperLabel() {}, addSourcePageLink() {return false;}, Set, Math};
vm.createContext(context);
vm.runInContext(renderCode, context);
context.render();
assert.equal(element('rows').children.length, 100);
assert.equal(element('chart').children.length, 100);
assert.equal(element('results-page').textContent, 'Page 1 of 3');
assert.equal(element('results-previous').disabled, true);
context.resultPage = 2;
context.render();
assert.equal(element('rows').children.length, 5);
assert.equal(element('results-page').textContent, 'Page 3 of 3');
assert.equal(element('results-next').disabled, true);
context.paper.value = 'paper-204';
context.render();
assert.equal(element('rows').children.length, 1);
assert.equal(element('results-page').textContent, 'Page 1 of 1');
context.comparisonPanel.open = false;
const previousPairRenders = pairRenders;
context.render();
assert.equal(pairRenders, previousPairRenders);
console.log('Metrics pagination passed');
