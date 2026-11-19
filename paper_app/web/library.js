"use strict";

const papersPage = location.pathname === "/papers";
const libraryPanel = element("library");
const libraryStatus = element("library-status");
const paperPicker = element("library-paper");
const paperSearch = element("paper-search");
const paperGroupFilter = element("paper-group-filter");
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

function groupMembers(value) {
  if (!value) return null;
  const groupId = Number(value);
  return new Set(libraryData.memberships
    .filter(item => item.group_id === groupId).map(item => item.paper_id));
}

function filterGroups() {
  libraryGroupMembers = groupMembers(groupPicker.value);
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
  const pdfLink = element("open-paper-pdf");
  pdfLink.hidden = !selected.has_pdf;
  if (selected.has_pdf) pdfLink.href = paperPDFURL(selected.id);
  else pdfLink.removeAttribute("href");
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

function paperFilename(item) {
  return item.path.split(/[\\/]/).pop();
}

function updatePaperOptions(selected = paperPicker.value) {
  const terms = paperSearch.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const members = groupMembers(paperGroupFilter.value);
  const papers = libraryData.papers.filter(item => {
    if (members && !members.has(item.id)) return false;
    const text = [item.title, item.authors, item.doi, item.venue, paperFilename(item)]
      .filter(Boolean).join(" ").toLowerCase();
    return terms.every(term => text.includes(term));
  });
  const options = papers.map(item => [item.id, item.title || paperFilename(item)]);
  const current = libraryData.papers.find(item => String(item.id) === selected);
  if (current && !papers.includes(current)) {
    options.unshift([current.id, `${current.title || paperFilename(current)} (selected)`]);
  }
  setOptions(paperPicker, options, papers.length ? "Choose a paper" : "No matching papers");
  if (current) paperPicker.value = selected;
  element("paper-search-status").textContent = terms.length || members
    ? `${papers.length} of ${libraryData.papers.length} papers match.` : "";
}

async function loadLibrary(paperId) {
  libraryData = await api(papersPage ? "paper-details" : "compare");
  if (papersPage) {
    setOptions(paperGroupFilter, libraryData.groups.map(item => [item.id, item.name]), "All groups");
    const requested = new URLSearchParams(location.search).get("paper");
    updatePaperOptions(paperId === undefined ? paperPicker.value || requested : String(paperId));
    if (paperId !== undefined) rememberPaperSelection();
    showPaper();
    return;
  }
  const papersById = new Map(libraryData.papers.map(item => [item.id, item]));
  setOptions(groupPicker, libraryData.groups.map(item => [item.id, item.name]), "All papers");
  rawMetrics = libraryData.metrics.map(row => ({
    ...row,
    title: papersById.get(row.paper_id)?.title,
    has_pdf: papersById.get(row.paper_id)?.has_pdf,
    originalValue: row.value,
    originalNumber: Number(row.value),
    originalUnit: row.unit,
  }));
  results.hidden = !rawMetrics.length;
  libraryGroupMembers = groupMembers(groupPicker.value);
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

paperSearch.addEventListener("input", () => {
  if (libraryData) updatePaperOptions();
});
paperGroupFilter.addEventListener("change", () => updatePaperOptions());
paperPicker.addEventListener("change", () => {
  libraryStatus.textContent = "";
  updatePaperOptions();
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

const relatedSearch = element("related-paper-search");
submit(relatedSearch, async () => {
  const searchStatus = element("related-paper-status");
  const results = element("related-paper-results");
  const download = element("download-related-dois");
  results.replaceChildren();
  download.hidden = true;
  searchStatus.textContent = "Searching Crossref titles…";
  try {
    const matches = await api("search-papers", {
      topic: relatedSearch.elements.topic.value.trim(),
      keywords: relatedSearch.elements.keywords.value.split("\n").map(line => line.trim()).filter(Boolean),
    });
    for (const { title, doi } of matches) {
      const item = add(results, "li", `${title} · `);
      add(item, "a", doi).href = `https://doi.org/${doi.split("/").map(encodeURIComponent).join("/")}`;
    }
    searchStatus.textContent = matches.length ? `${matches.length} matching papers.` : "No matching titles.";
    if (matches.length) {
      const content = matches.map(match => match.doi).join("\n") + "\n";
      download.href = `data:text/plain;charset=utf-8,${encodeURIComponent(content)}`;
      download.hidden = false;
    }
  } catch (error) {
    searchStatus.textContent = error.message;
  }
});

libraryPanel.hidden = !papersPage;
element("library-nav").hidden = false;
element(papersPage ? "papers-link" : "compare-link").setAttribute("aria-current", "page");
element("chart-group-label").hidden = papersPage;
if (papersPage) {
  document.title = "Papers";
  element("page-title").textContent = "Papers";
  for (const item of document.querySelectorAll(".compare-only")) item.hidden = true;
}
loadLibrary().catch(error => { (papersPage ? libraryStatus : status).textContent = error.message; });
