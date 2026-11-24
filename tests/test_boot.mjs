import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { Blob } from 'node:buffer';

const files = ['api.js', 'metrics.js', 'library.js', 'human-keys.js', 'documents.js', 'findings.js', 'goals.js', 'boot.js'];
const sources = files.map(name => fs.readFileSync(new URL(`../paper_app/web/${name}`, import.meta.url), 'utf8'));

for (const [path, expectedTitle] of [['/', 'Compare metrics'], ['/papers', 'Papers'], ['/documents', 'Markdown documents'], ['/account', 'Account']]) {
  const elements = new Map();
  function makeElement() {
    const fields = new Map();
    const listeners = new Map();
    return {value: '', textContent: '', hidden: false, disabled: false, checked: false, options: [], validity: {valid: true},
      selectedOptions: [], dataset: {}, classList: {toggle() {}},
      elements: new Proxy({}, {get(_target, key) {if (!fields.has(key)) fields.set(key, makeElement()); return fields.get(key);}}),
      addEventListener(type, listener) {listeners.set(type, listener);},
      fire(type) {return listeners.get(type)({preventDefault() {}});},
      setAttribute() {}, removeAttribute() {}, replaceChildren() {}, append() {}, reset() {}, closest() {return makeElement();},
      querySelector() {return makeElement();}, querySelectorAll() {return [];}, before() {}, setCustomValidity() {}};
  }
  const document = {title: '', getElementById(id) {if (!elements.has(id)) elements.set(id, makeElement()); return elements.get(id);},
    querySelectorAll() {return [];}, createElement() {return makeElement();}};
  const response = {account: null, papers: [], groups: [], memberships: [], metrics: [], comments: [],
    documents: [], archived_papers: [], document_targets: [], google_available: false,
    publishers: [], count: 0, total: 0, page: 1};
  const origin = 'http://127.0.0.1:8765';
  const invitation = {registration_path: '/api/ai/register/example',
    registration_url: 'https://papers.example.org/api/ai/register/example', username: 'reviewer', role: 'cloud'};
  const humanInvite = 'x'.repeat(43);
  const friendUrl = 'https://papers.example.org/account#invite=' + humanInvite;
  const hash = path === '/account' ? '#invite=' + humanInvite : '';
  let replaced;
  let clipboard = '';
  const context = {document, location: {pathname: path, search: '', href: origin + path + hash, origin, hash}, URLSearchParams,
    localStorage: {getItem() {return null;}}, history: {replaceState(_state, _title, url) {replaced = url;}},
    navigator: {clipboard: {async writeText(value) {clipboard = value;}}},
    FormData: function(form) {
      return ['username', 'role'].map(name => [name, form.elements[name].value]);
    },
    fetch: async (route, options) => {
      if (route === '/api/human-invitations') {
        if (!options) return {ok: true, json: async () => ({invitations: []})};
        assert.deepEqual(JSON.parse(options.body), {email: 'friend@example.org', role: 'member'});
        return {ok: true, json: async () => ({invitation_url: friendUrl, invite_id: 'fixture', role: 'member'})};
      }
      if (route === '/api/ai/invitations') {
        if (!options) return {ok: true, json: async () => ({agents: [], invitations: []})};
        assert.deepEqual(JSON.parse(options.body), {username: invitation.username, role: invitation.role});
        return {ok: true, json: async () => invitation};
      }
      return {ok: true, json: async () => response};
    },
    window: {addEventListener() {}}, addEventListener() {}, console, setTimeout, clearTimeout, Intl, URL, Blob};
  vm.createContext(context);
  for (let i = 0; i < files.length; i++) vm.runInContext(sources[i], context, {filename: files[i]});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(document.title, expectedTitle);
  const status = document.getElementById(path === '/account' ? 'account-status' : path === '/documents' ? 'document-status' : path === '/papers' ? 'library-status' : 'status');
  assert.equal(status.textContent, path === '/account' ?
    'Sign out if needed, then sign up with the email address that received this invitation.' : '',
  `Unexpected startup message on ${path}: ${status.textContent}`);
  if (path === '/account') {
    assert.equal(replaced, '/account');
    assert.equal(document.getElementById('human-key-signup-panel').open, true);
    assert.equal(document.getElementById('human-key-register').elements.invite.value, humanInvite);
    assert.equal(document.getElementById('signup').elements.invite.value, humanInvite);
    assert.equal(document.getElementById('human-invitation-panel').hidden, true);
    assert.equal(document.getElementById('ai-registration-panel').hidden, true);
    response.account = {id: 1, username: 'owner', role: 'user'};
    await vm.runInContext('loadLibrary()', context);
    assert.equal(document.getElementById('human-invitation-panel').hidden, false);
    const friendForm = document.getElementById('create-human-invitation');
    friendForm.elements.email.value = 'friend@example.org';
    friendForm.elements.role.value = 'member';
    await friendForm.fire('submit');
    assert.equal(document.getElementById('human-invitation-result').hidden, false);
    assert.equal(document.getElementById('human-invitation-access').textContent, 'Access level: Member');
    await document.getElementById('copy-human-invitation').fire('click');
    assert.equal(clipboard, friendUrl);
    assert.equal(document.getElementById('ai-registration-panel').hidden, false);
    const form = document.getElementById('create-ai-invitation');
    form.elements.username.value = invitation.username;
    form.elements.role.value = invitation.role;
    await form.fire('submit');
    assert.equal(document.getElementById('ai-invitation-result').hidden, false);
    await document.getElementById('copy-ai-invitation').fire('click');
    assert.ok(clipboard.includes(invitation.registration_url));
    assert.ok(clipboard.includes('paper_client.agent register --username reviewer'));
  }
}
console.log('All page startup scripts passed');
