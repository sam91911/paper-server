"use strict";

const documentPicker = element("document-picker");
const documentTopicFilter = element("document-topic-filter");
let activeDocumentTopic = new URLSearchParams(location.search).get("topic") || "";
let documentGoalOptionsSequence = 0;
const documentEditor = element("document-editor");
const documentFile = element("document-file");
const documentStatus = element("document-status");
const documentPreview = element("document-preview");
const newsWorkspace = globalThis.location?.pathname === "/news";
const discussionWorkspace = globalThis.location?.pathname === "/discussions";
const feedWorkspace = newsWorkspace || discussionWorkspace;
let editingDocument;
let editingRevision;
let documentParent = null;
let documentFinding = null;
let documentGoal = null;
let documentCommentSequence = 0;
let nextDocumentCommentBefore = null;
let documentLoadSequence = 0;
const documentCommentForm = element("document-comment-form");

function setDocumentReply(comment, findingId = null, goalId = null) {
  documentParent = comment?.id ?? null;
  documentFinding = findingId;
  documentGoal = goalId;
  const context = element("document-reply-context");
  context.hidden = !comment && findingId === null && goalId === null;
  context.textContent = comment ? `Replying to ${comment.author_name || "an unknown author"}`
    : goalId !== null ? `Discussing goal #${goalId}` : findingId === null ? "" : `Discussing finding #${findingId}`;
  element("cancel-document-reply").hidden = context.hidden;
  element("post-document-comment").textContent = comment ? "Post reply" : "Add comment";
  element("document-thread-schedule").hidden = Boolean(comment);
}

function renderDocumentComments(item) {
  element("document-discussion").hidden = !item;
  if (!item) return;
  if (discussionWorkspace) element("document-discussion").open = true;
  const comments = libraryData.comments.filter(comment => comment.document_id === item.id);
  if (documentParent !== null && !comments.some(comment => comment.id === documentParent && !comment.deleted)) setDocumentReply(null);
  renderComments(element("document-comments"), element("document-comment-summary"), comments,
    { document_id: item.id }, "document", documentStatus, comment => {
      setDocumentReply(comment);
      documentCommentForm.elements.body.focus();
    });
}

async function loadDocumentComments() {
  const sequence = ++documentCommentSequence;
  const data = libraryData;
  const item = selectedDocument();
  data.comments = [];
  nextDocumentCommentBefore = null;
  element("older-document-comments").hidden = true;
  element("document-discussion").hidden = true;
  if (item) {
    const result = await api(`document-comments?document_id=${item.id}`);
    if (sequence !== documentCommentSequence || data !== libraryData || selectedDocument()?.id !== item.id) return;
    data.comments = result.comments;
    nextDocumentCommentBefore = result.next_before;
    element("older-document-comments").hidden = !nextDocumentCommentBefore;
  }
  if (sequence === documentCommentSequence && data === libraryData) renderDocumentComments(item);
}

element("older-document-comments").addEventListener("click", async event => {
  const button = event.currentTarget;
  const sequence = documentCommentSequence;
  const data = libraryData;
  const item = selectedDocument();
  const cursor = nextDocumentCommentBefore;
  if (!item || !cursor) return;
  button.disabled = true;
  try {
    const result = await api(`document-comments?document_id=${item.id}&before=${cursor}`);
    if (sequence !== documentCommentSequence || data !== libraryData || selectedDocument()?.id !== item.id) return;
    data.comments = [...result.comments, ...data.comments];
    nextDocumentCommentBefore = result.next_before;
    button.hidden = !nextDocumentCommentBefore;
    renderDocumentComments(item);
  } catch (error) {
    documentStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

element("cancel-document-reply").addEventListener("click", () => setDocumentReply(null));
submit(documentCommentForm, async () => {
  const item = selectedDocument();
  const fields = documentCommentForm.elements;
  const line = fields.line.valueAsNumber;
  await api("comments", {
    document_id: item.id, body: fields.body.value, audience: fields.audience.value,
    doi_refs: doiLines(fields.doi_refs.value),
    recipients: recipientNames(fields.recipients.value), parent_id: documentParent,
    finding_id: documentFinding ?? undefined,
    goal_id: documentGoal ?? undefined,
    scheduled_at: documentParent === null ? scheduledTime(fields.scheduled_at) : undefined,
    location: Number.isSafeInteger(line) ? { kind: "document", id: item.id, position: line } : null,
  });
  if (selectedDocument()?.id === item.id) {
    documentCommentForm.reset();
    setDocumentReply(null);
  }
  await loadLibrary();
  documentStatus.textContent = "Comment posted.";
}, documentStatus);

function selectedDocument() {
  return libraryData.documents.find(item => item.id === Number(documentPicker.value));
}

function documentsInTopic() {
  return libraryData.documents.filter(item => !activeDocumentTopic ||
    item.topic?.toLowerCase() === activeDocumentTopic.toLowerCase());
}

function documentPageUrl(id, topic = activeDocumentTopic) {
  const params = new URLSearchParams();
  if (id) params.set("document", id);
  if (topic) params.set("topic", topic);
  return location.pathname + (params.toString() ? `?${params}` : "");
}

function renderDocumentContext(item) {
  const context = element("document-context");
  context.replaceChildren();
  context.hidden = !item?.topic && !item?.goal_link;
  if (item?.topic) add(context, "a", item.topic).href = documentPageUrl(null, item.topic);
  if (item?.goal_link) {
    if (item.topic) context.append(" · ");
    add(context, "a", item.goal_link.label).href = item.goal_link.url;
  }
}

async function loadDocumentGoalOptions(item, enabled) {
  const field = documentEditor.elements.linked_goal;
  const sequence = ++documentGoalOptionsSequence;
  field.disabled = true;
  const link = item?.goal_link;
  const selected = link ? `${link.kind}:${link.id}` : "";
  setOptions(field, link ? [[selected, link.label]] : [], "No linked goal");
  field.value = selected;
  if (!enabled) return;
  try {
    const {goals} = await api("document-goals");
    if (sequence !== documentGoalOptionsSequence) return;
    setOptions(field, goals.map(goal =>
      [`${goal.kind}:${goal.id}`, `${goal.kind === "research_goal" ? "Research" : "Agent"} · ${goal.label}`]),
    "No linked goal");
    field.value = goals.some(goal => `${goal.kind}:${goal.id}` === selected) ? selected : "";
    field.disabled = false;
  } catch (error) {
    if (sequence === documentGoalOptionsSequence) documentStatus.textContent = error.message;
  }
}

function renderDocumentFeed(item) {
  const list = element("news-list");
  list.replaceChildren();
  const entries = documentsInTopic();
  if (!entries.length) add(list, "li", activeDocumentTopic ? "No entries match this topic."
    : discussionWorkspace ? "No discussions yet." : "No news has been shared with you yet.");
  if (discussionWorkspace && element("discussion-sort").value === "top") {
    entries.sort((a, b) => b.vote_score - a.vote_score || b.id - a.id);
  }
  for (const entry of entries) {
    const row = add(list, "li");
    const link = add(row, "a", entry.title);
    link.href = documentPageUrl(entry.id);
    if (entry.id === item?.id) link.setAttribute("aria-current", "true");
    add(row, "p", `Shared by ${entry.owner_name} · ${entry.updated} UTC${discussionWorkspace ? ` · Score ${entry.vote_score}` : ""}`);
    if (discussionWorkspace) showSchedule(row, entry.scheduled_at);
  }
}

function renderDiscussionMeta(item) {
  const meta = element("discussion-meta");
  meta.hidden = !item;
  meta.replaceChildren();
  if (item) {
    showSchedule(meta, item.scheduled_at);
    voteControls(meta, item, {document_id: item.id}, documentStatus, () => renderDocumentFeed(item));
  }
}

function appendMarkdownLine(parent, line) {
  const pattern = /\[([^\[\]\n]+)\]\(([^\s)\[]+)\)|`([^`]+)`/g;
  let offset = 0;
  for (const match of line.matchAll(pattern)) {
    parent.append(line.slice(offset, match.index));
    if (match[3]) {
      add(parent, "code", match[3]);
    } else if (pdfPattern.test(match[2])) {
      inlinePdfLink(add(parent, "a", match[1]), "document", match[2], match[1]);
    } else if (/^https:\/\/doi\.org\/10\.\d{4,9}\//i.test(match[2])) {
      add(parent, "a", match[1]).href = match[2];
    } else if (/^\/documents\?document=[1-9]\d*&finding=[1-9]\d*$/.test(match[2])) {
      add(parent, "a", match[1]).href = match[2];
    } else {
      parent.append(match[0]);
    }
    offset = match.index + match[0].length;
  }
  parent.append(line.slice(offset));
}

function renderMarkdown(markdown) {
  documentPreview.replaceChildren();
  let block;
  let code;
  for (const line of markdown.split("\n")) {
    if (line.startsWith("```")) {
      code = code ? null : add(add(documentPreview, "pre"), "code");
      block = null;
    } else if (code) {
      code.append(line + "\n");
    } else if (!line.trim()) {
      block = null;
    } else if (/^#{1,6} /.test(line)) {
      const level = Math.min(6, line.indexOf(" ") + 2);
      appendMarkdownLine(add(documentPreview, `h${level}`), line.slice(line.indexOf(" ") + 1));
      block = null;
    } else if (/^[-*+] /.test(line)) {
      if (block?.tagName !== "UL") block = add(documentPreview, "ul");
      appendMarkdownLine(add(block, "li"), line.slice(2));
    } else {
      if (block?.tagName !== "P") block = add(documentPreview, "p");
      else block.append(" ");
      appendMarkdownLine(block, line);
    }
  }
}

async function ensureSelectedDocument() {
  const sequence = ++documentLoadSequence;
  const data = libraryData;
  const item = selectedDocument();
  if (!item) return null;
  if (typeof item.markdown === "string") return item;
  const result = await api(`document?id=${item.id}`);
  if (sequence !== documentLoadSequence || data !== libraryData || selectedDocument()?.id !== item.id) return undefined;
  Object.assign(item, result.document);
  return item;
}

async function openRequestedDocument() {
  const requested = new URLSearchParams(location.search);
  const id = requested.get("document");
  if (id === null) return;
  documentPicker.value = id;
  let item = selectedDocument();
  if (!item) {
    documentPicker.value = "";
    documentStatus.textContent = "This document is unavailable.";
    return;
  }
  item = await ensureSelectedDocument();
  if (!item) return;
  openDocument(item);
  const revision = requested.get("revision");
  const line = Number(requested.get("line"));
  if (Number.isSafeInteger(line) && line > 0) {
    const end = Number(requested.get("end") ?? line);
    const lines = item.markdown.split("\n");
    if (revision !== null && String(item.revision) !== revision) {
      documentStatus.textContent = "The cited revision has changed.";
    } else if (!Number.isSafeInteger(end) || end < line || end > lines.length) {
      documentStatus.textContent = `Source line ${line} is no longer present.`;
    } else {
      const label = line === end ? `Source line ${line}` : `Source lines ${line}–${end}`;
      const marker = add(documentPreview, "p", label, "document-location");
      add(add(documentPreview, "pre"), "code", lines.slice(line - 1, end).join("\n"));
      marker.scrollIntoView({ block: "center" });
    }
  }
  if (!discussionWorkspace && (requested.has("research") || requested.has("finding"))) {
    await globalThis.showRequestedResearch?.(requested.get("finding"));
  }
  if (!discussionWorkspace && requested.has("goal")) await globalThis.showRequestedGoal?.(requested.get("goal"));
}

function canEditDocument(item) {
  const account = libraryData.account;
  return Boolean(account && item && (item.can_manage || item.owner_id === account.id));
}

function openDocument(item, { create = false, edit = false } = {}) {
  const owns = canEditDocument(item);
  const canEdit = create || (owns && edit);
  editingDocument = create ? "new" : canEdit ? item.id : undefined;
  editingRevision = canEdit ? item?.revision : undefined;
  documentCommentForm.reset();
  setDocumentReply(null);
  globalThis.selectResearchDocument?.(discussionWorkspace ? null : item);
  globalThis.selectGoalDocument?.(discussionWorkspace ? null : item);
  element("review-document").hidden = !item || discussionWorkspace;
  renderDocumentComments(item);
  element("edit-document").hidden = !owns || canEdit;
  documentEditor.hidden = !canEdit;
  element("document-layout").classList.toggle("is-editing", Boolean(canEdit));
  element("document-preview-panel").hidden = !item && !create;
  element("document-browse-controls").open = !item && !create;
  closePdf("document");
  element("download-document").hidden = !item || discussionWorkspace;
  element("clone-document").hidden = !item || discussionWorkspace;
  element("document-owner").textContent = item
    ? `${item.owner_name}${item.owner_role === "user" ? "" : ` (${roleLabels[item.owner_role]})`} · ${audienceLabels[item.audience]} · Revision ${item.revision}`
    : "";
  documentStatus.textContent = "";
  documentEditor.reset();
  documentEditor.elements.topic.value = item?.topic || (create ? activeDocumentTopic : "");
  renderDocumentContext(item);
  void loadDocumentGoalOptions(item, canEdit);
  const isNews = Boolean(item?.source_url) || (newsWorkspace && create);
  const sourceLink = element("news-source-link");
  element("news-source").hidden = !item?.source_url;
  sourceLink.href = item?.source_url || "";
  element("preview-title").textContent = canEdit ? "Preview" : item?.title || "";
  element("news-source-field").hidden = !isNews;
  documentEditor.elements.source_url.required = isNews;
  documentEditor.elements.source_url.value = item?.source_url || "";
  element("save-document").textContent = isNews ? "Save news entry" : discussionWorkspace ? "Save discussion" : "Save document";
  const kind = discussionWorkspace ? "discussion" : isNews ? "news entry" : "document";
  element("document-editor-heading").textContent = `${create ? "New" : "Edit"} ${kind}`;
  if (discussionWorkspace) {
    element("discussion-schedule-field").hidden = false;
    documentEditor.elements.scheduled_at.value = localSchedule(item?.scheduled_at);
    renderDiscussionMeta(item);
  }
  if (feedWorkspace) renderDocumentFeed(item);
  documentEditor.elements.title.value = item?.title || "";
  documentEditor.elements.markdown.value = item?.markdown || "";
  selectAudience(documentEditor.elements.audience, item?.audience || "owner");
  documentEditor.elements.recipients.value = (item?.recipients || []).join(", ");
  renderMarkdown(item?.markdown || "");
}

async function showDocuments(accountChanged) {
  const account = libraryData.account;
  element("documents-workspace").hidden = !account;
  element("documents-sign-in").hidden = Boolean(account);
  element("news-feed").hidden = !feedWorkspace;
  if (newsWorkspace) {
    element("documents-sign-in").querySelector("a").textContent = "Sign in to share or discuss news";
    element("new-document").textContent = "Share news";
    element("document-picker-label").textContent = "News entry";
    element("document-browse-label").textContent = "Browse news";
  }
  if (discussionWorkspace) {
    document.body?.classList.add("discussion-page");
    element("news-feed-title").textContent = "Threads";
    element("discussion-sort-label").hidden = false;
    element("documents-sign-in").querySelector("a").textContent = "Sign in to join discussions";
    element("new-document").textContent = "New discussion";
    element("document-picker-label").textContent = "Discussion";
    element("document-browse-label").textContent = "Browse discussions";
  }
  const topics = new Map();
  for (const {topic} of libraryData.documents) if (topic) topics.set(topic.toLowerCase(), topic);
  if (activeDocumentTopic && !topics.has(activeDocumentTopic.toLowerCase())) {
    topics.set(activeDocumentTopic.toLowerCase(), activeDocumentTopic);
  }
  setOptions(documentTopicFilter, [...topics.values()].sort((a, b) => a.localeCompare(b))
    .map(topic => [topic, topic]), "All topics");
  documentTopicFilter.value = topics.get(activeDocumentTopic.toLowerCase()) || "";
  setOptions(documentPicker, documentsInTopic().map(item => [item.id, item.title]), "Choose a document");
  setOptions(documentFile, libraryData.papers.filter(paper => paper.has_pdf)
    .map(paper => [paper.id, paper.title || paperFilename(paper)]), "Choose a PDF");
  const requested = selectedDocument();
  const current = await ensureSelectedDocument();
  if (requested && !current) return;
  if (accountChanged || (!current && editingDocument !== "new")
      || (current && editingDocument && !canEditDocument(current))) openDocument(current);
  else {
    element("edit-document").hidden = !canEditDocument(current) || Boolean(editingDocument);
    if (feedWorkspace) renderDocumentFeed(current);
    if (discussionWorkspace) renderDiscussionMeta(current);
    renderDocumentComments(current);
  }
}

function insertMarkdown(text) {
  const field = documentEditor.elements.markdown;
  const start = field.selectionStart;
  const prefix = start > 0 && !/\s/.test(field.value[start - 1]) ? " " : "";
  const suffix = field.selectionEnd < field.value.length && !/\s/.test(field.value[field.selectionEnd]) ? " " : "";
  if (field.value.length - (field.selectionEnd - start) + prefix.length + text.length + suffix.length > field.maxLength) {
    documentStatus.textContent = "This link would exceed the Markdown length limit.";
    return;
  }
  field.setRangeText(prefix + text + suffix, start, field.selectionEnd, "end");
  renderMarkdown(field.value);
  field.focus();
}

documentPicker.addEventListener("change", () => {
  element("document-preview-panel").hidden = true;
  element("edit-document").hidden = true;
  documentEditor.hidden = true;
  ensureSelectedDocument().then(item => {
    if (item === undefined) return;
    openDocument(item);
    if (feedWorkspace || activeDocumentTopic) history.replaceState(null, "", documentPageUrl(item?.id));
    return loadDocumentComments();
  }).catch(error => { documentStatus.textContent = error.message; });
});
documentTopicFilter.addEventListener("change", () => {
  location.href = documentPageUrl(null, documentTopicFilter.value);
});
element("discussion-sort").addEventListener("change", () => renderDocumentFeed(selectedDocument()));
element("clone-document").addEventListener("click", () => {
  const item = selectedDocument();
  if (item) copyCloneCommand("documents", item.id, documentStatus);
});
element("edit-document").addEventListener("click", () => {
  const item = selectedDocument();
  if (canEditDocument(item)) {
    openDocument(item, {edit: true});
    documentEditor.elements.title.focus();
  }
});
element("cancel-document-edit").addEventListener("click", () => {
  const item = selectedDocument();
  openDocument(item);
  element(item ? "edit-document" : "new-document").focus();
});
element("new-document").addEventListener("click", () => {
  documentLoadSequence++;
  documentPicker.value = "";
  openDocument(null, { create: true });
  loadDocumentComments().catch(error => { documentStatus.textContent = error.message; });
  documentEditor.elements.title.focus();
});
documentEditor.elements.markdown.addEventListener("input", event => renderMarkdown(event.target.value));
element("insert-doi").addEventListener("click", () => {
  const field = element("document-doi");
  const doi = field.value.trim().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, "");
  if (!/^10\.\d{4,9}\/[^\s<>\x00-\x1f\x7f]{1,400}$/.test(doi)) {
    documentStatus.textContent = "Enter a DOI or DOI link.";
    field.focus();
    return;
  }
  const label = doi.replace(/[\[\]]/g, "");
  const url = doiURL(doi).replace(/\(/g, "%28").replace(/\)/g, "%29");
  insertMarkdown(`[${label}](${url})`);
});
function selectedDocumentPdf() {
  const paper = libraryData.papers.find(item => item.id === Number(documentFile.value));
  documentStatus.textContent = paper?.has_pdf ? "" : "Choose an accessible PDF.";
  return paper?.has_pdf ? paper : null;
}

element("view-document-pdf").addEventListener("click", () => {
  const paper = selectedDocumentPdf();
  if (paper) viewPdf("document", paperPDFURL(paper.id), paper.title || paperFilename(paper));
});

element("insert-file").addEventListener("click", () => {
  const paper = selectedDocumentPdf();
  if (!paper) return;
  const label = (paper.title || paperFilename(paper)).replace(/[\[\]\r\n]/g, " ");
  insertMarkdown(`[${label}](${paperPDFURL(paper.id)})`);
});
element("download-document").addEventListener("click", () => {
  const item = selectedDocument();
  if (!item) return;
  const url = URL.createObjectURL(new Blob([item.markdown], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${item.title.replace(/[\\/:*?"<>|]/g, "_")}.md`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
submit(documentEditor, async () => {
  if (!editingDocument) return;
  try {
    const fields = documentEditor.elements;
    const linkedGoal = fields.linked_goal.value;
    const oldGoal = selectedDocument()?.goal_link;
    const priorLink = oldGoal ? `${oldGoal.kind}:${oldGoal.id}` : "";
    const [goalKind, goalId] = linkedGoal.split(":");
    const topic = fields.topic.value.trim();
    const result = await api(discussionWorkspace ? "discussions" : "documents", {
      document_id: selectedDocument()?.id, revision: editingRevision, title: fields.title.value,
      audience: fields.audience.value, markdown: fields.markdown.value,
      recipients: recipientNames(fields.recipients.value), topic,
      ...(!fields.linked_goal.disabled && linkedGoal !== priorLink ? {
        research_goal_id: goalKind === "research_goal" ? Number(goalId) : null,
        agent_goal_id: goalKind === "agent_goal" ? Number(goalId) : null,
      } : {}),
      ...(fields.source_url.required ? {source_url: fields.source_url.value.trim()} : {}),
      ...(discussionWorkspace ? {scheduled_at: scheduledTime(fields.scheduled_at)} : {}),
    });
    const topicChanged = activeDocumentTopic && activeDocumentTopic.toLowerCase() !== topic.toLowerCase();
    if (topicChanged) activeDocumentTopic = "";
    await loadLibrary();
    documentPicker.value = String(result.document_id);
    const item = await ensureSelectedDocument();
    if (!item) return;
    openDocument(item);
    if (feedWorkspace || topicChanged || activeDocumentTopic) history.replaceState(null, "", documentPageUrl(item.id));
    await loadDocumentComments();
    documentStatus.textContent = item.source_url ? "News entry saved." : discussionWorkspace ? "Discussion saved." : "Document saved.";
  } catch (error) {
    documentStatus.textContent = error.message;
  }
});
