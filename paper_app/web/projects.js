"use strict";

const byId = id => document.getElementById(id);
const status = byId("project-status");
const picker = byId("project-picker").elements.project;
const edit = byId("project-edit");
const link = byId("project-link");
const proposalForm = byId("physical-proposal-form");
const tokenForm = byId("git-token-form");
const proposalLabels = {
  procedure: "Procedure", equipment: "Equipment and materials", procurement: "How to obtain them",
  estimated_cost: "Estimated cost", duration: "Expected duration", measurement: "Measurement plan",
  expected_data: "Expected data",
};
let account, projects = [], experiments = [], current, editingProposal, busy;

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
  byId("project-detail").hidden = !project;
  if (!project) return;
  picker.value = project.id;
  byId("project-title").textContent = `${project.title} · #${project.id}`;
  byId("project-description").textContent = project.description;
  byId("project-clone-url").value = location.origin + project.git_path;
  tokenForm.elements.kind.value = "projects";
  tokenForm.elements.resource_id.value = project.id;
  edit.hidden = project.access === "read";
  edit.elements.title.value = project.title;
  edit.elements.description.value = project.description;
  const owned = experiments.filter(experiment => experiment.owner_id === account.id &&
    !project.experiments.some(item => item.id === experiment.id));
  options(link.elements.experiment, owned, "Choose an experiment");
  link.hidden = edit.hidden || !owned.length;
  const branches = byId("project-branches");
  branches.replaceChildren();
  for (const [branch, commit] of Object.entries(project.branches)) {
    const row = add(branches, "li", `${branch} · ${commit.slice(0, 12)}`);
    const experiment = project.experiments.find(item => item.branch === branch);
    if (experiment) add(row, "a", ` · ${experiment.title}`).href = `/experiments?id=${experiment.id}`;
    const button = add(row, "button", "Copy branch clone");
    button.className = "secondary";
    button.addEventListener("click", () => copyCloneCommand("projects", project.id, status, branch));
  }
  byId("project-collaborators").hidden = !project.members;
  const members = byId("project-members");
  members.replaceChildren();
  for (const member of project.members || []) add(members, "li", `${member.username} · ${member.access}`);
}

async function selectProject(id) {
  const {project} = id ? await api(`projects?id=${id}`) : {};
  showProject(project);
  history.replaceState(null, "", (project ? `/projects?id=${project.id}` : "/projects") + location.hash);
}

async function loadProjects(id = current?.id) {
  ({projects} = await api("projects"));
  options(picker, projects, "Choose a project");
  await selectProject(id ?? projects[0]?.id);
  if (!editingProposal) resetProposal();
}

function resetProposal(proposal) {
  editingProposal = proposal;
  proposalForm.reset();
  const writable = projects.filter(project => project.access !== "read");
  options(proposalForm.elements.project_id, writable, "Private proposal");
  proposalForm.elements.project_id.disabled = Boolean(proposal);
  proposalForm.elements.project_id.value = proposal?.project_id || (!proposal && current?.access !== "read" ? current?.id || "" : "");
  if (!proposal) return;
  for (const name of ["title", ...Object.keys(proposalLabels)]) proposalForm.elements[name].value = proposal[name];
  proposalForm.elements.title.focus();
}

async function loadProposals() {
  const {proposals} = await api("physical-proposals");
  const list = byId("physical-proposal-list");
  list.replaceChildren();
  if (!proposals.length) add(list, "li", "No physical experiment proposals.");
  for (const proposal of proposals) {
    const row = add(list, "li");
    const detail = add(row, "details");
    add(detail, "summary", `${proposal.title} · Proposed`);
    if (proposal.project_id) {
      add(detail, "a", projects.find(item => item.id === proposal.project_id)?.title || "Project").href =
        `/projects?id=${proposal.project_id}`;
    }
    for (const [key, label] of Object.entries(proposalLabels)) {
      add(detail, "strong", label);
      add(detail, "p", proposal[key]).className = "goal-brief-text";
    }
    if (proposal.editable) add(detail, "button", "Edit proposal").addEventListener("click", () => resetProposal(proposal));
  }
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
submit("physical-proposal-form", async form => {
  const values = Object.fromEntries(["title", ...Object.keys(proposalLabels)].map(key => [key, form.elements[key].value]));
  const project_id = editingProposal ? editingProposal.project_id : Number(form.elements.project_id.value) || null;
  const reference = editingProposal ? {id: editingProposal.id, revision: editingProposal.revision} : {};
  await api("physical-proposals", {...reference, ...values, project_id});
  resetProposal();
  await loadProposals();
  status.textContent = "Physical experiment proposal saved.";
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
picker.addEventListener("change", () => run(async () => {
  await selectProject(picker.value);
  if (!editingProposal) resetProposal();
}));
byId("project-refresh").addEventListener("click", () => run(() => loadProjects()));
byId("physical-proposal-new").addEventListener("click", () => resetProposal());
byId("project-copy-clone").addEventListener("click", () =>
  copyCloneCommand("projects", current.id, status));

run(async () => {
  ({account} = await api("account"));
  byId("project-sign-in").hidden = Boolean(account);
  if (!account) return;
  ({experiments} = await api("experiments"));
  byId("project-workspace").hidden = false;
  const id = Number(new URLSearchParams(location.search).get("id"));
  await loadProjects(id > 0 ? id : undefined);
  await Promise.all([loadProposals(), loadTokens()]);
  if (location.hash === "#physical-proposals") byId("physical-proposals").open = true;
});
