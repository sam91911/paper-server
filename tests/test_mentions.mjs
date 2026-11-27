import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const handlers = new Map();
class Element {
  constructor() {
    this.attributes = new Map();
    this.children = [];
  }
  setAttribute(key, value) { this.attributes.set(key, value); }
  removeAttribute(key) { this.attributes.delete(key); }
  addEventListener() {}
  replaceChildren() { this.children = []; }
  append(child) { this.children.push(child); }
  after(child) { this.picker = child; }
  matches(selector) { return selector === '[data-mentions]'; }
  setRangeText(text, start, end) {
    this.value = this.value.slice(0, start) + text + this.value.slice(end);
  }
  focus() { document.activeElement = this; }
}

const editor = new Element();
const document = {
  activeElement: editor,
  getElementById: () => null,
  createElement: () => new Element(),
  addEventListener: (type, handler) => handlers.set(type, handler),
};
const requests = [];
let debounce;
const context = {document, location: {pathname: '/papers'},
  api: async path => {
    requests.push(path);
    return [{username: 'reader', display_name: 'Research Reader'}];
  },
  setTimeout: callback => { debounce = callback; },
  clearTimeout: () => { debounce = undefined; },
};
vm.runInNewContext(fs.readFileSync(new URL('../paper_app/web/mentions.js', import.meta.url), 'utf8'), context);
editor.value = 'Email me@re';
editor.selectionStart = editor.selectionEnd = editor.value.length;
handlers.get('input')({target: editor});
assert.equal(debounce, undefined);

editor.value = 'Hello @re, see the table.';
editor.selectionStart = editor.selectionEnd = 'Hello @re'.length;
handlers.get('input')({target: editor});
await debounce();
assert.deepEqual(requests, ['usernames?q=re']);
assert.equal(editor.picker.hidden, false);
assert.equal(editor.picker.children[0].textContent, '@reader · Research Reader');

const press = key => handlers.get('keydown')({target: editor, key, preventDefault() {}});
press('ArrowDown');
assert.equal(editor.picker.children[0].attributes.get('aria-selected'), 'true');
press('Enter');
assert.equal(editor.value, 'Hello @reader, see the table.');
assert.equal(editor.picker.hidden, true);
