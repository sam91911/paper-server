"use strict";

const researchPanel = element("research-workspace");
const findingForm = element("finding-form");
const findingEditor = element("finding-editor");
const evidenceList = element("finding-evidence");
const compareForm = element("finding-compare");
const researchStatus = element("research-status");
const findingList = element("finding-list");
const comparisonStatus = element("finding-comparison");
const findingKinds = { observation: "Observation or conclusion", baseline: "Published baseline", run_result: "Run result" };

let researchDocumentId = null;
let researchLoad = 0;
let researchComparison = 0;
let researchPending = false;
let editingFinding = null;

function selectResearchDocument(item) {
  researchDocumentId = item?.id ?? null;
  researchLoad++;
  researchComparison++;
  researchPending = false;
  researchPanel.open = false;
  researchPanel.hidden = !item;
  findingList.replaceChildren();
  element("research-experiments").replaceChildren();
  compareForm.hidden = true;
  comparisonStatus.textContent = "";
  researchStatus.textContent = "";
  resetFindingEditor();
}

function findingLabel(finding) {
  return `#${finding.id} · ${finding.statement.slice(0, 90)}`;
}

function evidenceLabel(ref) {
  if (ref.kind === "pdf") return `${ref.title} · PDF page ${ref.page}`;
  if (ref.kind === "run_artifact") return `${ref.title} · Run #${ref.run_id}, version ${ref.version}`;
  const lines = ref.start === ref.end ? `line ${ref.start}` : `lines ${ref.start}–${ref.end}`;
  return `${ref.title} · ${lines}, revision ${ref.revision}`;
}

function renderFinding(finding) {
  const card = add(findingList, "article", undefined, "paper-comment");
  card.id = `finding-${finding.id}`;
  const title = add(card, "h3", `#${finding.id} · ${findingKinds[finding.kind]}`);
  title.tabIndex = -1;
  const role = roleLabels[finding.author_role];
  add(card, "p", finding.author_role === "user" ? finding.author_name : `${finding.author_name} · ${role}`);
  add(card, "p", finding.statement, "comment-body");
  if (finding.value) {
    add(card, "p", `${finding.metric}: ${finding.value} ${finding.unit}`);
    add(card, "p", `Measurement conditions: ${finding.conditions}`);
  }
  const references = add(card, "ul");
  for (const ref of finding.evidence) {
    const entry = add(references, "li");
    const link = add(entry, "a", evidenceLabel(ref));
    link.href = ref.url;
    if (ref.stale) add(entry, "span", " · Citation needs review");
    if (ref.kind === "run_artifact") {
      add(entry, "a", " · View experiment and run").href = `/experiments?id=${ref.experiment_id}`;
    }
  }
  const discuss = add(card, "button", "Discuss", "secondary");
  discuss.type = "button";
  discuss.addEventListener("click", () => {
    element("document-discussion").open = true;
    setDocumentReply(null, finding.id);
    documentCommentForm.elements.body.focus();
  });
  if (finding.can_edit || finding.author_id === libraryData.account?.id) {
    const edit = add(card, "button", "Edit finding", "secondary");
    edit.type = "button";
    edit.addEventListener("click", () => {
      resetFindingEditor(finding);
      findingEditor.open = true;
      findingForm.elements.statement.focus();
    });
  }
  return title;
}

async function loadResearchWorkspace(requestedFinding = null) {
  const id = researchDocumentId;
  if (id === null) return;
  const sequence = ++researchLoad;
  const isCurrent = () => researchLoad === sequence && researchDocumentId === id;
  researchPending = true;
  researchStatus.textContent = "Loading research findings…";
  try {
    const result = await api(`research-findings?document_id=${id}`);
    if (!isCurrent()) return;
    const experiments = element("research-experiments");
    experiments.replaceChildren();
    const create = add(experiments, "a", `Link an experiment to document #${id}`);
    create.href = `/experiments?document=${id}`;
    if (result.experiments.length) {
      const list = add(experiments, "ul");
      for (const experiment of result.experiments) {
        add(add(list, "li"), "a", experiment.title).href = `/experiments?id=${experiment.id}`;
      }
    }
    findingList.replaceChildren();
    let requestedTitle;
    for (const finding of result.findings) {
      const heading = renderFinding(finding);
      if (String(finding.id) === requestedFinding) requestedTitle = heading;
    }
    const options = result.findings.map(finding => [finding.id, findingLabel(finding)]);
    for (const side of ["left", "right"]) setOptions(compareForm.elements[side], options, "Choose a finding");
    compareForm.hidden = options.length < 2;
    researchComparison++;
    comparisonStatus.textContent = "";
    researchStatus.textContent = requestedFinding && !requestedTitle ? "This finding is unavailable."
      : result.findings.length ? "" : "No findings yet.";
    requestedTitle?.focus();
  } catch (error) {
    if (!isCurrent()) return;
    findingList.replaceChildren();
    element("research-experiments").replaceChildren();
    compareForm.hidden = true;
    researchStatus.textContent = error.message;
  } finally {
    if (isCurrent()) researchPending = false;
  }
}

async function showRequestedResearch(findingId) {
  researchPanel.open = true;
  await loadResearchWorkspace(findingId);
}

researchPanel.addEventListener("toggle", () => {
  if (researchPanel.open && !researchPending) loadResearchWorkspace();
});

function addEvidenceRow(ref = {}) {
  const row = add(evidenceList, "fieldset");
  add(row, "legend", "Evidence reference");
  const kind = add(add(row, "label", "Source type "), "select");
  const kinds = [["pdf", "PDF page"], ["document", "Markdown lines"], ["run_artifact", "Run artifact version"]];
  setOptions(kind, kinds);
  kind.value = ref.kind || "pdf";
  const targetLabel = add(row, "label");
  const targetCaption = add(targetLabel, "span", "Source ");
  const target = add(targetLabel, "select");
  const versionLabel = add(row, "label", "Artifact version ID ");
  const version = add(versionLabel, "input");
  version.value = ref.kind === "run_artifact" ? ref.id : "";
  version.placeholder = "Shown under Experiments";

  function position(label, value) {
    const wrapper = add(row, "label", label);
    const input = add(wrapper, "input");
    input.type = "number";
    input.min = "1";
    input.step = "1";
    input.value = value ?? "";
    return { wrapper, input };
  }

  const page = position("PDF page ", ref.page);
  const start = position("First line ", ref.start);
  const end = position("Last line (optional) ", ref.end);
  const revision = position("Cited document revision ", ref.revision);
  const remove = add(row, "button", "Remove reference", "secondary");
  remove.type = "button";
  remove.addEventListener("click", () => row.remove());

  const sourceDocuments = libraryData?.documents || [];
  function showFields(selectedId) {
    const isDocument = kind.value === "document";
    const isPDF = kind.value === "pdf";
    targetLabel.hidden = !isDocument && !isPDF;
    targetCaption.textContent = isDocument ? "Document " : "PDF ";
    versionLabel.hidden = isDocument || isPDF;
    page.wrapper.hidden = !isPDF;
    for (const field of [start, end, revision]) field.wrapper.hidden = !isDocument;
    if (isPDF || isDocument) {
      const options = isPDF
        ? (libraryData?.papers || []).filter(paper => paper.has_pdf)
          .map(paper => [paper.id, paper.title || paperFilename(paper)])
        : sourceDocuments.map(doc => [doc.id, `${doc.title} (revision ${doc.revision})`]);
      if (selectedId !== undefined && ref.title && !options.some(([id]) => id === selectedId)) {
        options.push([selectedId, ref.title]);
      }
      setOptions(target, options, "Choose a source");
      if (selectedId !== undefined) target.value = String(selectedId);
    }
  }
  kind.addEventListener("change", () => showFields());
  target.addEventListener("change", () => {
    if (kind.value === "document") {
      revision.input.value = sourceDocuments.find(doc => String(doc.id) === target.value)?.revision ?? "";
    }
  });
  showFields(ref.id);

  row.citation = () => {
    if (kind.value === "pdf") return {kind: kind.value, id: Number(target.value), page: Number(page.input.value)};
    if (kind.value === "run_artifact") return {kind: kind.value, id: Number(version.value)};
    const first = Number(start.input.value);
    return {kind: kind.value, id: Number(target.value), start: first,
      end: end.input.value ? Number(end.input.value) : first, revision: Number(revision.input.value)};
  };
}

function resetFindingEditor(finding = null) {
  editingFinding = finding;
  findingForm.reset();
  element("finding-editor-label").textContent = finding ? `Edit finding #${finding.id}` : "Add finding";
  element("cancel-finding-edit").hidden = !finding;
  for (const field of ["statement", "kind", "metric", "value", "unit", "conditions"]) {
    if (finding) findingForm.elements[field].value = finding[field];
  }
  element("verify-baseline").hidden = findingForm.elements.kind.value !== "baseline";
  evidenceList.replaceChildren();
  if (researchDocumentId !== null) {
    for (const ref of finding?.evidence ?? [{}]) addEvidenceRow(ref);
  }
}

findingForm.elements.kind.addEventListener("change", () => {
  element("verify-baseline").hidden = findingForm.elements.kind.value !== "baseline";
});
element("add-evidence").addEventListener("click", () => {
  if (evidenceList.children.length < 20) addEvidenceRow();
});
element("cancel-finding-edit").addEventListener("click", () => resetFindingEditor());

submit(findingForm, async () => {
  const documentId = researchDocumentId;
  if (documentId === null) return;
  const fields = findingForm.elements;
  const result = await api("research-findings", {
    document_id: documentId, id: editingFinding?.id, revision: editingFinding?.revision,
    statement: fields.statement.value, kind: fields.kind.value, verified_baseline: fields.verified_baseline.checked,
    metric: fields.metric.value, value: fields.value.value.trim(), unit: fields.unit.value,
    conditions: fields.conditions.value, evidence: [...evidenceList.children].map(row => row.citation()),
  });
  if (documentId !== researchDocumentId) return;
  resetFindingEditor();
  findingEditor.open = false;
  await loadResearchWorkspace(String(result.id));
}, researchStatus);

submit(compareForm, async () => {
  const id = researchDocumentId;
  if (id === null) return;
  const sequence = ++researchComparison;
  const left = compareForm.elements.left.value;
  const right = compareForm.elements.right.value;
  comparisonStatus.textContent = "Comparing…";
  try {
    const result = await api(`research-findings?document_id=${id}&left=${left}&right=${right}`);
    if (sequence !== researchComparison) return;
    const {difference, reasons, findings: selected} = result.comparison;
    const values = selected.map(finding => `#${finding.id}: ${finding.value ? `${finding.value} ${finding.unit}` : "qualitative"}`);
    const unit = selected[0].unit === "%" ? "percentage points" : selected[0].unit;
    const summary = difference === null ? reasons.join(" ") : `Absolute difference: ${difference} ${unit}.`;
    comparisonStatus.textContent = `${values.join(" · ")}. ${summary}`;
  } catch (error) {
    if (sequence === researchComparison) comparisonStatus.textContent = error.message;
  }
}, comparisonStatus);
