"use strict";

const byId = (id) => document.getElementById(id);
const statusText = byId("skill-status");
const search = byId("skill-search");
const form = byId("skill-form");
const list = byId("skill-results");
const detailPanel = byId("skill-detail");
const editor = byId("skill-editor");
const more = byId("more-skills");
const edit = byId("edit-skill");
const archive = byId("archive-skill");
let account;
let selected;
let editing;
let cursor;
let searchParameters;
let listRequest = 0;
let detailRequest = 0;

function report(error) {
  statusText.textContent = error.message;
  if (error.status === 401) {
    byId("skill-sign-in").hidden = false;
    byId("skill-library").hidden = true;
  }
}

async function loadSkills(append = false) {
  const request = ++listRequest;
  if (!append) {
    searchParameters = {
      q: search.elements.q.value,
      tag: search.elements.tag.value,
      archived: search.elements.view.value === "archived" ? "1" : "0",
    };
    more.hidden = true;
  }
  const params = new URLSearchParams(searchParameters);
  if (append) params.set("after", cursor);
  more.disabled = true;
  try {
    const data = await api(`skills?${params}`);
    if (request !== listRequest) return;
    if (!append) list.replaceChildren();
    for (const skill of data.skills) {
      const item = document.createElement("li");
      const link = document.createElement("button");
      link.type = "button";
      link.className = "secondary";
      link.textContent = skill.title;
      link.addEventListener("click", () => openSkill(skill.id));
      item.append(link);
      if (skill.description) {
        const description = document.createElement("p");
        description.textContent = skill.description;
        item.append(description);
      }
      list.append(item);
    }
    if (!list.childElementCount) {
      const empty = document.createElement("li");
      empty.textContent = "No skills found.";
      list.append(empty);
    }
    cursor = data.next_after;
    more.hidden = cursor === null;
  } catch (error) {
    if (request === listRequest) report(error);
  } finally {
    if (request === listRequest) more.disabled = false;
  }
}

function showSkill(skill) {
  selected = skill;
  const owned = skill.can_manage || skill.owner_id === account.id;
  byId("skill-title").textContent = skill.title;
  byId("skill-description").textContent = skill.description;
  byId("skill-meta").textContent = [skill.id === "default" ? "Built in" : `ID ${skill.id}`,
    ...skill.tags, ...(skill.archived ? ["Archived"] : [])].join(" · ");
  byId("skill-markdown").textContent = skill.markdown;
  edit.hidden = !owned || skill.archived;
  archive.hidden = !owned;
  archive.textContent = skill.archived ? "Restore" : "Archive";
  detailPanel.hidden = false;
  editor.hidden = true;
  byId("skill-browse-controls").open = false;
  byId("skill-title").focus();
}

async function openSkill(id) {
  const request = ++detailRequest;
  statusText.textContent = "";
  try {
    const data = await api(`skills/${id}`);
    if (request === detailRequest) showSkill(data.skill);
  } catch (error) {
    if (request === detailRequest) report(error);
  }
}

function openEditor(skill) {
  ++detailRequest;
  editing = skill;
  form.reset();
  if (skill) {
    for (const name of ["title", "description", "markdown", "audience"]) {
      form.elements[name].value = skill[name];
    }
    form.elements.tags.value = skill.tags.join(", ");
    form.elements.recipients.value = skill.recipients.join(", ");
  }
  statusText.textContent = "";
  byId("skill-editor-title").textContent = skill ? "Edit skill" : "New skill";
  detailPanel.hidden = true;
  editor.hidden = false;
  byId("skill-browse-controls").open = false;
  form.elements.title.focus();
}

async function saveSkill(data, button) {
  const request = ++detailRequest;
  button.disabled = true;
  try {
    const result = await api("skills", data);
    if (request === detailRequest) {
      showSkill(result.skill);
      statusText.textContent = "Skill saved.";
    }
    await loadSkills();
  } catch (error) {
    if (request === detailRequest) report(error);
  } finally {
    button.disabled = false;
  }
}

search.addEventListener("submit", (event) => {
  event.preventDefault();
  statusText.textContent = "";
  loadSkills();
});
more.addEventListener("click", () => loadSkills(true));
byId("new-skill").addEventListener("click", () => openEditor(null));
byId("default-skill").addEventListener("click", () => openSkill("default"));
edit.addEventListener("click", () => openEditor(selected));
archive.addEventListener("click", () => {
  saveSkill({ action: selected.archived ? "restore" : "archive", id: selected.id, revision: selected.revision }, archive);
});
byId("cancel-skill").addEventListener("click", () => {
  ++detailRequest;
  editor.hidden = true;
  if (selected) showSkill(selected);
  else byId("skill-browse-controls").open = true;
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  for (const name of ["tags", "recipients"]) {
    data[name] = data[name].split(",").map((value) => value.trim()).filter(Boolean);
  }
  Object.assign(data, editing ? { action: "update", id: editing.id, revision: editing.revision } : { action: "create" });
  saveSkill(data, event.submitter);
});

async function initialize() {
  try {
    ({ account } = await api("account"));
    byId("skill-sign-in").hidden = Boolean(account);
    if (account) {
      byId("skill-library").hidden = false;
      await loadSkills();
      if (new URLSearchParams(location.search).get("skill") === "default") await openSkill("default");
    }
  } catch (error) {
    report(error);
  }
}
initialize();
