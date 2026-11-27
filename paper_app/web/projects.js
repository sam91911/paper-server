"use strict";

const byId = id => document.getElementById(id);
const status = byId("project-status");
const picker = byId("project-picker").elements.project;
const edit = byId("project-edit");
const link = byId("project-link");
const tokenForm = byId("git-token-form");
const branchPicker = byId("project-browser-branch");
const browserStatus = byId("project-browser-status");
const previousCommits = byId("project-history-previous");
const nextCommits = byId("project-history-next");
let browserRequest = 0, browserResult, browserView = "files";
let account, projects = [], experiments = [], current, busy;

function add(parent, tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  parent.append(node);
  return node;
}

async function run(action) {
  if (busy) return;
  busy = true;
  status.textContent = "";
  try {
    await action();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    busy = false;
  }
}

function submit(id, action) {
  byId(id).addEventListener("submit", event => {
    event.preventDefault();
    run(() => action(event.currentTarget || byId(id)));
  });
}

function options(field, records, placeholder) {
  field.replaceChildren();
  if (placeholder) add(field, "option", placeholder).value = "";
  for (const {id, title} of records) add(field, "option", title).value = id;
}

function showProject(project) {
  current = project;
  ++browserRequest;
  byId("project-detail").hidden = !project;
  byId("project-repository-controls").hidden = !project;
  const settings = byId("project-settings-menu");
  settings.hidden = !project;
  settings.open = false;
  byId("project-empty").hidden = Boolean(project);
  picker.value = project?.id || "";
  if (!project) return;
  byId("project-title").textContent = `${project.title} · #${project.id}`;
  byId("project-description").textContent = project.description;
  byId("project-physical-experiments").href = `/physical-experiments?project=${project.id}`;
  const deletion = byId("project-delete-settings");
  deletion.hidden = project.access !== "owner";
  deletion.open = false;
  byId("project-clone-url").value = location.origin + project.git_path;
  tokenForm.elements.kind.value = "projects";
  tokenForm.elements.resource_id.value = project.id;
  edit.hidden = project.access === "read";
  edit.elements.title.value = project.title;
  edit.elements.description.value = project.description;
  const owned = experiments.filter(experiment => experiment.owner_id === account.id &&
    !project.experiments.some(item => item.id === experiment.id));
  options(link.elements.experiment, owned, "Choose an experiment");
  link.hidden = edit.hidden || !owned.length || !project.default_branch;
  const branches = byId("project-branches");
  branches.replaceChildren();
  for (const [branch, commit] of Object.entries(project.branches)) {
    const row = add(branches, "li", `${branch} · ${commit.slice(0, 12)}`);
    const experiment = project.experiments.find(item => item.branch === branch);
    if (experiment) add(row, "a", ` · ${experiment.title}`).href = `/experiments?id=${experiment.id}`;
    browserButton(row, "Browse branch", () => {
      branchPicker.value = branch;
      navigateBrowser();
    });
    const button = add(row, "button", "Copy branch clone");
    button.className = "secondary";
    button.addEventListener("click", () => copyCloneCommand("projects", project.id, status, branch));
  }
  byId("project-collaborators").hidden = !project.members;
  const members = byId("project-members");
  members.replaceChildren();
  for (const member of project.members || []) add(members, "li", `${member.username} · ${member.access}`);
  options(branchPicker, Object.keys(project.branches).map(branch => ({id: branch, title: branch})));
  branchPicker.disabled = !project.default_branch;
  branchPicker.value = project.default_branch || "";
  const params = new URLSearchParams(location.search);
  const matchesProject = params.get("id") === String(project.id);
  if (matchesProject) {
    const branch = params.get("branch");
    if (Object.hasOwn(project.branches, branch)) branchPicker.value = branch;
  }
  setBrowserView(matchesProject && params.get("view") === "commits" ? "commits" : "files");
  loadBrowser(matchesProject ? {
    path: params.get("path") || "", commit: params.get("commit") || undefined,
    offset: Number(params.get("offset")) || 0,
  } : {});
}

function browserButton(parent, text, action) {
  const button = add(parent, "button", text, "secondary");
  button.type = "button";
  button.addEventListener("click", action);
  return button;
}

function setBrowserView(view) {
  browserView = view;
  const files = view === "files";
  byId("project-code-view").setAttribute("aria-pressed", String(files));
  byId("project-history-view").setAttribute("aria-pressed", String(!files));
  byId("project-file-view").hidden = !files;
  byId("project-history-panel").hidden = files;
}

function browserUrl({path = "", commit, offset = 0, view = browserView} = {}) {
  const params = new URLSearchParams({id: current.id});
  if (branchPicker.value && branchPicker.value !== current.default_branch) params.set("branch", branchPicker.value);
  if (path) params.set("path", path);
  if (commit) params.set("commit", commit);
  if (offset) params.set("offset", offset);
  if (view !== "files") params.set("view", view);
  return `/projects?${params}`;
}

function navigateBrowser(options = {}) {
  const url = browserUrl(options);
  if (location.pathname + location.search !== url) history.pushState(null, "", url);
  setBrowserView(options.view || browserView);
  return loadBrowser(options);
}

function repositoryLink(parent, text, options) {
  const anchor = add(parent, "a", text);
  anchor.href = browserUrl(options);
  anchor.addEventListener("click", event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigateBrowser(options);
  });
  return anchor;
}

async function loadBrowser({path = "", commit, offset = 0} = {}) {
  if (!current) return;
  const request = ++browserRequest;
  const params = new URLSearchParams({id: current.id, branch: branchPicker.value, path, offset});
  if (commit) params.set("commit", commit);
  browserResult = undefined;
  browserStatus.textContent = "Loading repository…";
  for (const id of ["project-path", "project-files", "project-history"]) byId(id).replaceChildren();
  byId("project-preview").hidden = true;
  byId("project-file-table").hidden = true;
  byId("project-latest-commit").textContent = "";
  byId("project-tip").hidden = true;
  previousCommits.disabled = nextCommits.disabled = true;
  try {
    const result = await api(`project-browser?${params}`);
    if (request !== browserRequest) return;
    browserResult = result;
    renderBrowser(result, commit);
  } catch (error) {
    if (request === browserRequest) browserStatus.textContent = error.message;
  }
}

function renderBrowser(result, commit) {
  if (result.kind === "empty") {
    browserStatus.textContent = "This repository is empty. Push your first commit to populate the project.";
    add(byId("project-history"), "li", "No commits yet.");
    return;
  }
  browserStatus.textContent = `Viewing ${result.branch} at ${result.commit.slice(0, 12)}`;
  byId("project-tip").hidden = result.commit === result.head;
  const breadcrumb = byId("project-path");
  const segments = result.path ? result.path.split("/") : [];
  if (segments.length) repositoryLink(breadcrumb, current.title, {commit});
  else add(breadcrumb, "strong", current.title);
  for (const [index, segment] of segments.entries()) {
    breadcrumb.append(" / ");
    if (index === segments.length - 1) add(breadcrumb, "strong", segment);
    else repositoryLink(breadcrumb, segment, {path: segments.slice(0, index + 1).join("/"), commit});
  }

  const revision = byId("project-latest-commit");
  const headline = result.history.find(entry => entry.id === result.commit);
  if (headline) add(revision, "span", `${headline.subject || "(no commit message)"} · ${headline.author} · `);
  repositoryLink(revision, "View commits", {path: result.path, commit, view: "commits"});
  const files = byId("project-files");
  if (result.kind === "directory") {
    byId("project-file-table").hidden = false;
    if (segments.length) {
      const row = add(files, "tr");
      repositoryLink(add(row, "td"), "..", {path: segments.slice(0, -1).join("/"), commit});
      add(row, "td", "Parent directory");
    }
    if (!result.entries.length) {
      const cell = add(add(files, "tr"), "td", "This directory is empty.");
      cell.colSpan = 2;
    }
    for (const entry of result.entries) {
      const row = add(files, "tr");
      const name = add(row, "td");
      if (entry.kind === "other") add(name, "span", entry.name);
      else repositoryLink(name, entry.name, {path: [...segments, entry.name].join("/"), commit});
      add(row, "td", {directory: "Directory", file: "File", other: "Other"}[entry.kind]);
    }
  } else {
    const preview = byId("project-preview");
    preview.hidden = false;
    if (result.preview === "text") preview.textContent = result.text || "Empty file";
    else {
      const message = result.preview === "binary" ? "Binary file" : "File is too large to preview";
      preview.textContent = `${message} · ${result.size.toLocaleString()} bytes`;
    }
  }

  const history = byId("project-history");
  if (!result.history.length) add(history, "li", "No commits on this page.");
  for (const entry of result.history) {
    const row = add(history, "li");
    repositoryLink(row, entry.subject || "(no commit message)", {commit: entry.id, view: "files"});
    const date = new Date(entry.date);
    const byline = add(row, "p", `${entry.id.slice(0, 12)} · ${entry.author} · ${date.toLocaleString()}`, "record-byline");
    byline.title = entry.id;
  }
  previousCommits.disabled = result.previous_offset === null;
  nextCommits.disabled = result.next_offset === null;
}

branchPicker.addEventListener("change", () => navigateBrowser());
byId("project-tip").addEventListener("click", () => navigateBrowser({view: "files"}));
function selectBrowserView(view) {
  const {path, commit, head} = browserResult || {};
  if (current) navigateBrowser({path, commit: commit !== head ? commit : undefined, view});
}
byId("project-code-view").addEventListener("click", () => selectBrowserView("files"));
byId("project-history-view").addEventListener("click", () => selectBrowserView("commits"));
function pageHistory(offset) {
  if (browserResult && offset !== null) {
    const {path, commit, head} = browserResult;
    navigateBrowser({path, commit: commit !== head ? commit : undefined, offset});
  }
}
previousCommits.addEventListener("click", () => pageHistory(browserResult?.previous_offset ?? null));
nextCommits.addEventListener("click", () => pageHistory(browserResult?.next_offset ?? null));

async function selectProject(id) {
  const {project} = id ? await api(`projects?id=${id}`) : {};
  showProject(project);
  if ((new URLSearchParams(location.search).get("id") || "") !== String(project?.id || "")) {
    history.replaceState(null, "", (project ? `/projects?id=${project.id}` : "/projects") + location.hash);
  }
}

async function loadProjects(id = current?.id) {
  ({projects} = await api("projects"));
  options(picker, projects, "Choose a project");
  await selectProject(id);
}

async function loadTokens(result) {
  const {tokens} = result || await api("git-tokens");
  const list = byId("git-token-list");
  list.replaceChildren();
  for (const token of tokens) {
    const row = add(list, "li", `${token.kind}/${token.resource_id} · ${token.access} · Expires ${new Date(token.expires * 1000).toLocaleString()}`);
    const revoke = add(row, "button", "Revoke");
    revoke.className = "secondary";
    revoke.addEventListener("click", () => run(async () => {
      byId("git-token-secret").value = "";
      byId("new-git-token").hidden = true;
      await loadTokens(await api("git-tokens", {action: "revoke", id: token.id}));
      status.textContent = "Token revoked.";
    }));
  }
}

submit("new-project", async form => {
  const {project} = await api("projects", {action: "create", title: form.elements.title.value,
    description: form.elements.description.value});
  form.reset();
  byId("new-project-panel").open = false;
  await loadProjects(project.id);
  status.textContent = "Project created.";
});
submit("project-edit", async form => {
  const {project} = await api("projects", {action: "edit", id: current.id, revision: current.revision,
    title: form.elements.title.value, description: form.elements.description.value});
  await loadProjects(project.id);
  status.textContent = "Project saved.";
});
submit("project-link", async form => {
  const {project} = await api("projects", {action: "link_experiment", id: current.id,
    experiment_id: Number(form.elements.experiment.value)});
  showProject(project);
  status.textContent = "Experiment branch created from main.";
});
submit("project-share", async form => {
  const {project} = await api("projects", {action: "share", id: current.id,
    username: form.elements.username.value, access: form.elements.access.value});
  form.reset();
  showProject(project);
  status.textContent = "Collaborator access updated.";
});
submit("git-token-form", async form => {
  const {kind, resource_id, access, days} = form.elements;
  const result = await api("git-tokens", {action: "create", kind: kind.value,
    resource_id: Number(resource_id.value), access: access.value, days: Number(days.value)});
  const secret = byId("git-token-secret");
  secret.value = result.token;
  byId("new-git-token").hidden = false;
  secret.select();
  await loadTokens(result);
  status.textContent = "Git token created.";
});
window.addEventListener("popstate", () => {
  const id = new URLSearchParams(location.search).get("id");
  if (current && String(current.id) === id) showProject(current);
  else run(() => selectProject(id));
});
picker.addEventListener("change", () => run(async () => {
  await selectProject(picker.value);
}));
byId("project-refresh").addEventListener("click", () => run(() => loadProjects()));
byId("project-delete").addEventListener("click", () => run(async () => {
  const project = current;
  if (!project || project.access !== "owner") return;
  if (!window.confirm(`Delete “${project.title}” and its Git history? This cannot be undone.`)) return;
  await api("projects", {action: "delete", id: project.id, revision: project.revision, git_revision: project.git_revision});
  byId("git-token-secret").value = "";
  byId("new-git-token").hidden = true;
  await loadProjects(null);
  await loadTokens();
  status.textContent = "Project deleted.";
}));
byId("project-copy-clone").addEventListener("click", () =>
  copyCloneCommand("projects", current.id, status, branchPicker.value === current.default_branch ? "" : branchPicker.value));

run(async () => {
  if (location.hash === "#physical-proposals") {
    const project = new URLSearchParams(location.search).get("id");
    location.replace(project ? `/physical-experiments?project=${encodeURIComponent(project)}` : "/physical-experiments");
    return;
  }
  ({account} = await api("account"));
  byId("project-sign-in").hidden = Boolean(account);
  if (!account) return;
  ({experiments} = await api("experiments"));
  byId("project-workspace").hidden = false;
  const id = Number(new URLSearchParams(location.search).get("id"));
  await loadProjects(id > 0 ? id : undefined);
  await loadTokens();
});
