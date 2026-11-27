"use strict";

const byId = id => document.getElementById(id);
const form = byId("physical-proposal-form");
const status = byId("physical-proposal-status");
const projectId = Number(new URLSearchParams(location.search).get("project")) || null;
const labels = {
  procedure: "Procedure", equipment: "Equipment and materials", procurement: "How to obtain them",
  estimated_cost: "Estimated cost", duration: "Expected duration", measurement: "Measurement plan",
  expected_data: "Expected data",
};
let projects = [], selected, busy = false;

function add(parent, type, text) {
  const node = document.createElement(type);
  if (text !== undefined) node.textContent = text;
  parent.append(node);
  return node;
}

function editProposal(proposal) {
  selected = proposal;
  form.reset();
  const picker = form.elements.project_id;
  picker.replaceChildren();
  add(picker, "option", "Private proposal").value = "";
  for (const project of projects) {
    if (project.access !== "read") add(picker, "option", project.title).value = project.id;
  }
  picker.disabled = Boolean(proposal);
  const writableProject = projects.some(item => item.id === projectId && item.access !== "read");
  picker.value = proposal ? proposal.project_id ?? "" : writableProject ? projectId : "";
  if (!proposal) return;
  for (const field of ["title", ...Object.keys(labels)]) form.elements[field].value = proposal[field];
  form.elements.title.focus();
}

async function loadProposals() {
  const {proposals} = await api("physical-proposals");
  const list = byId("physical-proposal-list");
  list.replaceChildren();
  const visible = proposals.filter(proposal => !projectId || proposal.project_id === projectId);
  if (!visible.length) add(list, "li", "No physical experiment proposals.");
  for (const proposal of visible) {
    const detail = add(add(list, "li"), "details");
    add(detail, "summary", `${proposal.title} · Proposed`);
    if (proposal.project_id) {
      add(detail, "a", projects.find(item => item.id === proposal.project_id)?.title || "Project").href =
        `/projects?id=${proposal.project_id}`;
    }
    for (const [field, title] of Object.entries(labels)) {
      add(detail, "strong", title);
      add(detail, "p", proposal[field]).className = "goal-brief-text";
    }
    if (proposal.editable) {
      const edit = add(detail, "button", "Edit proposal");
      edit.type = "button";
      edit.addEventListener("click", () => {
        form.hidden = false;
        editProposal(proposal);
      });
    }
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  try {
    const values = Object.fromEntries(["title", ...Object.keys(labels)].map(key => [key, form.elements[key].value]));
    const reference = selected ? {id: selected.id, revision: selected.revision} : {};
    const project_id = selected ? selected.project_id : Number(form.elements.project_id.value) || null;
    await api("physical-proposals", {...reference, ...values, project_id});
    if (projectId && project_id !== projectId) {
      location.assign("/physical-experiments");
      return;
    }
    editProposal();
    form.hidden = true;
    await loadProposals();
    status.textContent = "Physical experiment proposal saved.";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    busy = false;
  }
});
byId("physical-proposal-new").addEventListener("click", () => {
  editProposal();
  form.hidden = false;
  form.elements.title.focus();
});
byId("physical-proposal-cancel").addEventListener("click", () => {
  form.hidden = true;
  byId("physical-proposal-new").focus();
});

async function start() {
  const {account} = await api("account");
  if (!account) {
    byId("physical-proposal-sign-in").hidden = false;
    return;
  }
  ({projects} = await api("projects"));
  byId("physical-proposal-filter").hidden = !projectId;
  editProposal();
  await loadProposals();
  byId("physical-proposal-workspace").hidden = false;
}
start().catch(error => { status.textContent = error.message; });
