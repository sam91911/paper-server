"use strict";

const $ = id => document.getElementById(id);
const picker = $("experiments");
const detail = $("detail");
const retryButton = $("retry-experiment-load");
const newExperiment = $("new-experiment");
const experimentForm = $("experiment-form");
const runForm = $("run-form");
const itemForm = $("item-form");
const grantForm = $("grant-form");
const workspaceForm = $("experiment-workspace-form");
const detailForms = [runForm, itemForm, grantForm, ...(workspaceForm ? [workspaceForm] : [])];
const requested = globalThis.location ? new URLSearchParams(location.search) : null;
const submitButton = form => form.querySelector("button");

let listLoading = false;
let listReady = false;
let detailLoading = false;
let saving = false;
let displayedExperimentId = null;
let detailRequest = 0;
let retryLoad = null;
let experimentRevision = null;
let editingRun = null;
let runBrief = null;

function text(tag, content, parent) {
  const element = document.createElement(tag);
  element.textContent = content;
  parent.append(element);
  return element;
}

function addOption(select, value, label) {
  const option = text("option", label, select);
  option.value = value;
}

for (const select of document.querySelectorAll(".audience")) {
  for (const [value, label] of [
    ["owner", "Owner only"],
    ["users", "Trusted humans"],
    ["local", "Trusted humans and local AI"],
    ["all", "All trusted accounts"],
  ]) {
    addOption(select, value, label);
  }
}

function selectedExperimentId() {
  return Number(picker.value) || null;
}

function updateControls() {
  picker.disabled = saving || listLoading || !listReady;
  submitButton(experimentForm).disabled = saving || listLoading || detailLoading;
  for (const form of detailForms) {
    submitButton(form).disabled = saving || displayedExperimentId === null;
  }
  retryButton.disabled = saving || listLoading;
}

function setStatus(message, retry = null) {
  $("status").textContent = message;
  retryLoad = retry;
  retryButton.hidden = retry === null;
}

function editRun(run = null) {
  editingRun = run;
  runForm.reset();
  $("run-form-heading").textContent = run ? `Edit run #${run.id}` : "New run";
  $("cancel-run-edit").hidden = !run;
  if (run) {
    for (const field of ["title", "description", "methods", "settings", "status", "audience"]) {
      runForm.elements[field].value = run[field];
    }
  } else if (runBrief) {
    runForm.elements.methods.value = runBrief.approach;
    runForm.elements.settings.value = runBrief.conditions;
  }
}

function previewFile(url, parent) {
  const preview = text("details", "", parent);
  text("summary", "Preview text", preview);
  const source = text("pre", "", preview);
  source.className = "goal-brief-text";
  preview.addEventListener("toggle", async () => {
    if (!preview.open || source.textContent) return;
    source.textContent = "Loading…";
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("Could not open this file.");
      const content = await response.text();
      source.textContent = content.includes("\0") ? "Download this binary file to inspect it." : content || "Empty file.";
    } catch (error) {
      source.textContent = error.message;
    }
  });
}

function archiveTree(files, base, parent) {
  const tree = text("ul", "", parent);
  const folders = new Map([["", tree]]);
  for (const file of files) {
    const parts = file.path.split("/");
    let key = "";
    for (const name of parts.slice(0, -1)) {
      const folder = key + name + "/";
      if (!folders.has(folder)) {
        const section = text("details", "", text("li", "", folders.get(key)));
        text("summary", name, section);
        folders.set(folder, text("ul", "", section));
      }
      key = folder;
    }
    const row = text("li", "", folders.get(key));
    const name = parts.at(-1);
    const link = text("a", name, row);
    link.href = `${base}/entry?path=${encodeURIComponent(file.path)}`;
    link.download = name;
    if (file.size <= 128 * 1024) previewFile(link.href, row);
  }
}

function browseArchive(version, parent) {
  const panel = text("details", "", parent);
  text("summary", "Browse archive files", panel);
  const contents = text("div", "", panel);
  const base = `/research-versions/${version.id}`;
  panel.addEventListener("toggle", async () => {
    if (!panel.open || contents.childElementCount) return;
    const status = text("p", "Loading files…", contents);
    try {
      const response = await fetch(`${base}/entries`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not list files in this archive.");
      const {commit, files} = result;
      status.textContent = commit ? `Git commit ${commit}` : files.length ? "" : "No files to display.";
      status.hidden = !status.textContent;
      archiveTree(files, base, contents);
    } catch (error) {
      status.textContent = error.message;
    }
  });
}

function renderExperiment(result) {
  const {experiment, runs, items, brief} = result;
  if (runBrief?.id !== brief?.id) {
    runBrief = brief;
    editRun();
  }
  $("experiment-title").textContent = `${experiment.title} (#${experiment.id}, revision ${experiment.revision})`;
  $("experiment-description").textContent = experiment.description;
  experimentRevision = experiment.revision;
  const workspace = $("experiment-workspace");
  workspace.replaceChildren();
  if (experiment.research_document_id) {
    const link = text("a", brief ? `Open ${brief.stage} goal and brief #${brief.id}` : "Open research document", workspace);
    link.href = `/documents?document=${experiment.research_document_id}${brief ? `&goal=${brief.goal_id}` : "&research=1"}`;
  }
  if (workspaceForm) {
    workspaceForm.hidden = !result.can_edit || Boolean(brief);
    workspaceForm.elements.research_document_id.value = experiment.research_document_id ?? "";
  }
  runForm.hidden = !result.can_edit;
  const runList = $("runs");
  const runSelect = $("run-select");
  const selectedRun = runSelect.value;
  runList.replaceChildren();
  runSelect.replaceChildren();
  addOption(runSelect, "", "Experiment level");
  for (const run of runs) {
    const box = text("article", "", runList);
    text("h4", `${run.title} (#${run.id}) · ${run.status}`, box);
    if (run.brief_id) text("p", `Tested brief #${run.brief_id}`, box);
    if (run.description) text("p", run.description, box);
    if (run.methods) {
      text("h5", "Methods and reproduction commands", box);
      text("pre", run.methods, box).className = "goal-brief-text";
    }
    if (run.settings) {
      text("h5", "Environment and settings", box);
      text("pre", run.settings, box).className = "goal-brief-text";
    }
    if (run.can_edit) {
      const edit = text("button", "Edit run", box);
      edit.type = "button";
      edit.addEventListener("click", () => {
        editRun(run);
        runForm.elements.title.focus();
      });
    }
    addOption(runSelect, run.id, run.title);
  }
  runSelect.value = runs.some(run => String(run.id) === selectedRun) ? selectedRun : "";

  const itemList = $("items");
  itemList.replaceChildren();
  for (const item of items) {
    const run = runs.find(row => row.id === item.run_id);
    const box = text("article", "", itemList);
    text("h4", item.title, box);
    text("p", `${item.kind} · #${item.id}, revision ${item.revision}${run ? ` · Run #${run.id}: ${run.title}` : ""}`, box);
    for (const version of item.versions) {
      const line = text("p", `v${version.number} (version ID ${version.id}) · ${version.description} ${version.external_ref} `, box);
      if (version.sha256) {
        const link = text("a", `Download ${version.filename}`, line);
        link.href = `/research-versions/${version.id}/file`;
        if (version.filename.toLowerCase().endsWith(".zip")) browseArchive(version, box);
        else if (version.size <= 128 * 1024 && /\.(csv|tsv|txt|jsonl?|log|md|ya?ml|toml|py|sh)$/i.test(version.filename)) {
          previewFile(link.href, box);
        }
      }
    }
  }
}

function hideExperiment() {
  displayedExperimentId = null;
  detail.hidden = true;
  updateControls();
}

async function showExperiment(id, saved = false) {
  const request = ++detailRequest;
  detailLoading = id !== null;
  hideExperiment();
  const prefix = saved ? "Saved. " : "";
  if (id === null) {
    setStatus(prefix.trim());
    return;
  }
  const isCurrent = () => request === detailRequest && id === selectedExperimentId();
  setStatus(`${prefix}Loading experiment…`);
  try {
    const result = await api(`experiment-detail?id=${id}`);
    if (!isCurrent()) return;
    renderExperiment(result);
    displayedExperimentId = id;
    detail.hidden = false;
    setStatus(prefix.trim());
  } catch (error) {
    if (!isCurrent()) return;
    setStatus(`${prefix}Could not load experiment. ${error.message}`, () => showExperiment(id, saved));
  } finally {
    if (isCurrent()) {
      detailLoading = false;
      updateControls();
    }
  }
}

async function refreshExperiments(id = null, saved = false) {
  const prefix = saved ? "Saved. " : "";
  ++detailRequest;
  listLoading = true;
  hideExperiment();
  setStatus(`${prefix}Loading experiments…`);
  try {
    const result = await api("experiments");
    picker.replaceChildren();
    addOption(picker, "", "Choose");
    for (const item of result.experiments) {
      addOption(picker, item.id, `${item.title} (#${item.id})`);
    }
    picker.value = id === null ? "" : String(id);
    listReady = true;
    if (id !== null && selectedExperimentId() === null) {
      setStatus(`${prefix}Experiment unavailable.`);
      return;
    }
    await showExperiment(selectedExperimentId(), saved);
  } catch (error) {
    setStatus(`${prefix}Could not load experiments. ${error.message}`, () => refreshExperiments(id, saved));
  } finally {
    listLoading = false;
    updateControls();
  }
}

function submit(form, save, reload) {
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const id = displayedExperimentId;
    if (saving || listLoading || detailLoading || (form !== experimentForm && (id === null || id !== selectedExperimentId()))) {
      return;
    }
    saving = true;
    updateControls();
    setStatus("Saving…");
    try {
      const result = await save(form.elements, id);
      form.reset();
      await reload(result, id);
    } catch (error) {
      setStatus(error.message);
    } finally {
      saving = false;
      updateControls();
    }
  });
}

picker.addEventListener("change", () => {
  for (const form of detailForms) form.reset();
  runBrief = null;
  editRun();
  $("run-select").replaceChildren();
  return showExperiment(selectedExperimentId());
});

retryButton.addEventListener("click", () => retryLoad?.());
$("cancel-run-edit").addEventListener("click", () => editRun());

submit(experimentForm, fields => api("experiments", {
  title: fields.title.value,
  description: fields.description.value,
  audience: fields.audience.value,
  paper_id: fields.paper_id.value ? Number(fields.paper_id.value) : null,
  research_document_id: fields.research_document_id.value ? Number(fields.research_document_id.value) : null,
}), result => {
  newExperiment.open = false;
  for (const form of detailForms) form.reset();
  editRun();
  return refreshExperiments(result.id, true);
});

if (workspaceForm) {
  submit(workspaceForm, (fields, id) => api("experiments", {
    id, revision: experimentRevision,
    research_document_id: fields.research_document_id.value ? Number(fields.research_document_id.value) : null,
  }), (_result, id) => showExperiment(id, true));
}

submit(runForm, (fields, id) => api("experiment-runs", {
  experiment_id: id,
  id: editingRun?.id,
  revision: editingRun?.revision,
  title: fields.title.value,
  description: fields.description.value,
  methods: fields.methods.value,
  settings: fields.settings.value,
  status: fields.status.value,
  audience: fields.audience.value,
}), (_result, id) => {
  editRun();
  return showExperiment(id, true);
});

submit(itemForm, async (fields, id) => {
  const file = fields.file.files[0];
  const data = {
    experiment_id: id,
    run_id: fields.run_id.value ? Number(fields.run_id.value) : null,
    kind: fields.kind.value,
    title: fields.title.value,
    description: fields.description.value,
    audience: fields.audience.value,
    external_ref: fields.external_ref.value,
  };
  if (fields.id.value) {
    data.id = Number(fields.id.value);
    data.revision = Number(fields.revision.value);
  }
  if (!file) return api("research-items", data);

  data.filename = file.name;
  const response = await fetch("/api/research-upload", {
    method: "POST",
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Research-Metadata": encodeURIComponent(JSON.stringify(data)),
    },
    body: file,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Upload failed.");
  return result;
}, (_result, id) => showExperiment(id, true));

function names(value) {
  return value.split(",").map(name => name.trim()).filter(Boolean);
}

submit(grantForm, fields => api("research-grants", {
  kind: fields.kind.value,
  id: Number(fields.id.value),
  readers: names(fields.readers.value),
  editors: names(fields.editors.value),
}), (_result, id) => showExperiment(id, true));

async function loadTools() {
  const result = await api("research-tools");
  for (const tool of result.tools) {
    text("p", `${tool.name} ${tool.version} · ${tool.description}`, $("tools"));
  }
  for (const tool of result.host_tools) {
    text("p", `${tool.name}: ${tool.available ? tool.version || "available" : "not installed"}`, $("host-tools"));
  }
}

if (requested?.has("document")) {
  experimentForm.elements.research_document_id.value = requested.get("document");
  newExperiment.open = true;
}
refreshExperiments(Number(requested?.get("id")) || null);
loadTools().catch(error => { $("tools-status").textContent = error.message; });
