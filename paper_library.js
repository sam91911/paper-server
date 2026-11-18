"use strict";

const papersPage = document.body.dataset.page === "papers";
const libraryPanel = element("library");
const libraryStatus = element("library-status");
const paperPicker = element("library-paper");
const groupPicker = element("library-group");
const metadataForm = element("metadata");
const lookupPaperForm = element("lookup-paper");
const lookupForm = element("lookup");
const lookupResults = element("lookup-results");
const metadataLabels = {
  title: "Title", authors: "Authors", year: "Year", venue: "Venue",
  publisher: "Publisher", doi: "DOI", source: "Source",
};
const metadataFields = Object.keys(metadataLabels).filter(field => field !== "source");
let lookupSequence = 0;
let libraryData;
let metadataSource = "";

async function api(route, data) {
  const options = data === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
  const response = await fetch(`/api/${route}`, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}

function setOptions(picker, items, emptyLabel) {
  const selected = picker.value;
  picker.replaceChildren();
  add(picker, "option", emptyLabel).value = "";
  for (const [id, label] of items) add(picker, "option", label).value = String(id);
  if ([...picker.options].some(option => option.value === selected)) picker.value = selected;
}

function setMetadata(data) {
  for (const field of metadataFields) metadataForm.elements[field].value = data[field] || "";
  metadataSource = data.source || "";
  element("metadata-source").textContent = metadataSource ? `Source: ${metadataSource}` : "";
}

function selectedPaper() {
  return libraryData?.papers.find(item => item.id === Number(paperPicker.value));
}

function filterGroups() {
  const groupId = Number(groupPicker.value);
  libraryGroupMembers = groupId ? new Set(libraryData.memberships
    .filter(item => item.group_id === groupId).map(item => item.paper_id)) : null;
  render();
}

function showSavedMetadata(paper) {
  const details = element("saved-metadata");
  details.replaceChildren();
  for (const [field, label] of Object.entries(metadataLabels)) {
    if (!paper[field]) continue;
    add(details, "dt", label);
    add(details, "dd", paper[field]);
  }
  element("no-metadata").hidden = details.children.length > 0;
}

function showPaper() {
  lookupSequence++;
  const selected = selectedPaper();
  paperPicker.title = selected ? selected.title || selected.path : "";
  element("paper-detail").hidden = !selected;
  lookupResults.replaceChildren();
  lookupForm.reset();
  if (!selected) return;
  showSavedMetadata(selected);
  setMetadata(selected);
  lookupForm.elements.query.value = selected.doi;
  const memberships = new Set(libraryData.memberships
    .filter(item => item.paper_id === selected.id).map(item => item.group_id));
  const choices = element("group-options");
  choices.replaceChildren();
  for (const group of libraryData.groups) {
    const label = add(choices, "label");
    const input = add(label, "input");
    input.type = "checkbox";
    input.value = group.id;
    input.checked = memberships.has(group.id);
    add(label, "span", group.name);
  }
  if (!libraryData.groups.length) add(choices, "p", "Create a group to assign this paper.");

  const comments = element("comments");
  comments.replaceChildren();
  for (const comment of libraryData.comments.filter(item => item.paper_id === selected.id)) {
    const form = add(comments, "form");
    const field = add(add(form, "label", `Updated ${comment.updated} UTC`), "textarea");
    field.value = comment.body;
    field.required = true;
    field.maxLength = 20000;
    add(form, "button", "Save comment");
    submit(form, () => updateLibrary("comments", {
      paper_id: selected.id, comment_id: comment.id, body: field.value,
    }, "Comment updated."));
  }
}

function rememberPaperSelection() {
  const url = new URL(location.href);
  if (paperPicker.value) url.searchParams.set("paper", paperPicker.value);
  else url.searchParams.delete("paper");
  history.replaceState(null, "", url);
}

async function loadLibrary(paperId) {
  libraryData = await api(papersPage ? "paper-details" : "compare");
  if (papersPage) {
    setOptions(paperPicker, libraryData.papers.map(item => [
      item.id, item.title || item.path.split(/[\\/]/).pop(),
    ]), "Choose a paper");
    if (paperId !== undefined) {
      paperPicker.value = String(paperId);
      rememberPaperSelection();
    } else if (!paperPicker.value) {
      const requested = new URLSearchParams(location.search).get("paper");
      if (requested !== null && [...paperPicker.options].some(option => option.value === requested)) {
        paperPicker.value = requested;
      }
    }
    showPaper();
    return;
  }
  const titles = new Map(libraryData.papers.map(item => [item.id, item.title]));
  setOptions(groupPicker, libraryData.groups.map(item => [item.id, item.name]), "All papers");
  rawMetrics = libraryData.metrics.map(row => ({
    ...row,
    title: titles.get(row.paper_id),
    originalValue: row.value,
    originalNumber: Number(row.value),
    originalUnit: row.unit,
  }));
  results.hidden = !rawMetrics.length;
  libraryGroupMembers = groupPicker.value
    ? new Set(libraryData.memberships.filter(item => item.group_id === Number(groupPicker.value))
      .map(item => item.paper_id)) : null;
  refreshGroups();
  if (!rawMetrics.length) status.textContent = "The library has no metric rows. Import a CSV or extract a PDF into the database.";
}

async function updateLibrary(route, data, message) {
  await api(route, data);
  await loadLibrary();
  libraryStatus.textContent = message;
}

function submit(form, action) {
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (form.dataset.busy) return;
    form.dataset.busy = "true";
    try {
      await action();
    } catch (error) {
      libraryStatus.textContent = error.message;
    } finally {
      delete form.dataset.busy;
    }
  });
}

paperPicker.addEventListener("change", () => {
  libraryStatus.textContent = "";
  rememberPaperSelection();
  showPaper();
});
groupPicker.addEventListener("change", filterGroups);
metadataForm.addEventListener("input", () => {
  metadataSource = "Manual";
  element("metadata-source").textContent = "Source: Manual";
});

async function importPaper(file) {
  const response = await fetch("/api/papers", {
    method: "POST",
    headers: {
      "Content-Type": "application/pdf",
      "X-Paper-Filename": encodeURIComponent(file.name),
    },
    body: file,
  });
  const imported = await response.json();
  if (!response.ok) throw new Error(imported.error || "PDF import failed.");
  return imported;
}

submit(element("pdf-import"), async () => {
  const field = element("paper-pdf");
  const files = [...field.files];
  if (!files.length) return;
  const button = element("import-pdf-button");
  const report = element("import-results");
  report.replaceChildren();
  report.hidden = false;
  button.disabled = field.disabled = true;
  let importedCount = 0;
  let lastPaperId;
  try {
    for (const [index, file] of files.entries()) {
      libraryStatus.textContent = `Importing PDF ${index + 1} of ${files.length}…`;
      try {
        const imported = await importPaper(file);
        importedCount++;
        lastPaperId = imported.paper_id;
        const result = imported.has_text
          ? `${imported.metrics} metric candidate(s) found`
          : "saved with no extractable text";
        add(report, "li", `${file.name} · ${result}`);
      } catch (error) {
        add(report, "li", `${file.name} · Import failed: ${error.message}`);
      }
    }
    field.value = "";
    const summary = `Imported ${importedCount} of ${files.length} PDF(s).`;
    if (importedCount) {
      try {
        await loadLibrary(lastPaperId);
      } catch (error) {
        throw new Error(`${summary} The library could not refresh: ${error.message}`);
      }
    }
    libraryStatus.textContent = summary;
  } finally {
    button.disabled = field.disabled = false;
  }
});

submit(element("create-group"), async () => {
  const form = element("create-group");
  await updateLibrary("groups", { name: form.elements.name.value }, "Group created.");
  form.reset();
});
submit(element("membership"), () => updateLibrary("memberships", {
  paper_id: selectedPaper().id,
  groups: [...element("group-options").querySelectorAll("input:checked")].map(input => Number(input.value)),
}, "Groups saved."));
submit(element("add-comment"), async () => {
  const field = element("new-comment");
  await updateLibrary("comments", { paper_id: selectedPaper().id, body: field.value }, "Comment added.");
  field.value = "";
});
submit(metadataForm, () => updateLibrary("metadata", {
  ...Object.fromEntries(metadataFields.map(key => [key, metadataForm.elements[key].value.trim()])),
  paper_id: selectedPaper().id,
  source: metadataSource || "Manual",
}, "Metadata saved."));
async function findMetadata(query) {
  const sequence = ++lookupSequence;
  lookupResults.replaceChildren();
  libraryStatus.textContent = "Looking up Crossref metadata…";
  let matches;
  try {
    matches = await api("lookup", query);
  } catch (error) {
    if (sequence === lookupSequence) throw error;
    return;
  }
  if (sequence !== lookupSequence) return;
  libraryStatus.textContent = matches.length ? "Select a result, then save the metadata." : "Crossref returned no matches.";
  for (const match of matches) {
    const item = add(lookupResults, "li");
    const label = [match.title, match.authors, match.year, match.venue, match.doi].filter(Boolean).join(" · ");
    const button = add(item, "button", label || "Untitled result");
    button.type = "button";
    button.addEventListener("click", () => {
      setMetadata(match);
      libraryStatus.textContent = "Result selected. Save metadata to update this paper.";
    });
  }
}

submit(lookupPaperForm, () => findMetadata({ paper_id: selectedPaper().id }));
submit(lookupForm, () => findMetadata({
  kind: lookupForm.elements.kind.value, query: lookupForm.elements.query.value,
}));

libraryPanel.hidden = !papersPage;
element("library-nav").hidden = false;
element(papersPage ? "papers-link" : "compare-link").setAttribute("aria-current", "page");
element("chart-group-label").hidden = papersPage;
if (papersPage) {
  document.title = "Papers";
  element("page-title").textContent = "Papers";
  for (const item of document.querySelectorAll(".compare-only")) item.hidden = true;
}
element("csv-picker").hidden = true;
loadLibrary().catch(error => { (papersPage ? libraryStatus : status).textContent = error.message; });
