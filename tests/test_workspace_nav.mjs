import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../paper_app/web/workspace-nav.js", import.meta.url), "utf8");
const saved = new Map();
function start(compact) {
  const button = {
    hidden: true, attributes: {},
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(type, action) { this[type] = action; },
    focus() { this.focused = true; },
  };
  const navigation = {hidden: false, addEventListener(type, action) { this[type] = action; }};
  const document = {
    body: {dataset: {}},
    getElementById: id => id === "workspace-nav-toggle" ? button : navigation,
  };
  vm.runInNewContext(source, {document, matchMedia: () => ({matches: compact, addEventListener() {}}),
    localStorage: {getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value)}});
  return {button, navigation, body: document.body};
}

const desktop = start(false);
assert.equal(desktop.navigation.hidden, false);
desktop.button.click();
assert.equal(desktop.navigation.hidden, true);
assert.equal(desktop.body.dataset.sidebar, "hidden");
assert.equal(desktop.button.attributes["aria-expanded"], "false");
const nextPage = start(false);
assert.equal(nextPage.navigation.hidden, true);
nextPage.button.click();
nextPage.navigation.keydown({key: "Escape"});
assert.equal(nextPage.button.focused, true);
assert.equal(nextPage.navigation.hidden, true);
saved.clear();
assert.equal(start(true).navigation.hidden, true);
