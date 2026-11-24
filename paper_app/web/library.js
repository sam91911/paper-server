"use strict";

const papersPage = location.pathname === "/papers";
const accountPage = location.pathname === "/account";
const documentsPage = location.pathname === "/documents";
const comparePage = !papersPage && !accountPage && !documentsPage;
const libraryPanel = element("library");
const libraryStatus = element("library-status");
const paperPicker = element("library-paper");
const paperSearch = element("paper-search");
const paperGroupFilter = element("paper-group-filter");
const paperPublisherFilter = element("paper-publisher-filter");
const paperYearFrom = element("paper-year-from");
const paperYearTo = element("paper-year-to");
const paperComments = element("paper-comments");
const paperArchive = element("paper-archive");
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
let commentLoadSequence = 0;
let nextCommentBefore = null;
const paperPageSize = 100;
let paperPage = 1;
let paperCatalog = null;
let paperCatalogSequence = 0;
let paperCatalogTimer;
let paperLibraryRevision = 0;
let paperSelection = "";
let paperSelectionSequence = 0;
let paperDetails = null;
let paperTargets = null;
let paperTargetRequest = null;
let paperArchiveRequest = null;
let libraryData;
let metadataSource = "";
const commentDrafts = new Map();
const newComment = element("new-comment");
const commentForm = element("add-comment");
const accountForm = element("account-form");
const accountStatus = element("account-status");
const paperAccessForm = element("paper-access");
const roleLabels = { user: "Trusted human", member: "Member", local: "Local AI", cloud: "Cloud AI" };
const audienceLabels = {
  owner: "Owner only",
  users: "Trusted human accounts",
  local: "Trusted human and local AI accounts",
  all: "All trusted accounts, including cloud AI",
  ai: "Local AI accounts only (legacy)",
};

function fillAudiences(select, current = "owner") {
  for (const [value, label] of Object.entries(audienceLabels)) {
    if (value !== "ai" || current === "ai") add(select, "option", label).value = value;
  }
  if (current === "inherit") add(select, "option", "Same access as paper (legacy)").value = current;
  select.value = current;
}
for (const select of document.querySelectorAll(".audience-options")) fillAudiences(select);

function selectAudience(select, value) {
  select.replaceChildren();
  fillAudiences(select, value);
}

function showAccount() {
  const account = libraryData.account;
  element("account-summary").textContent = account ? `${account.display_name || account.username} · ${roleLabels[account.role]}` : "Sign in";
  element("human-key-entry").hidden = Boolean(account);
  element("password-account-options").hidden = Boolean(account);
  element("sign-out").hidden = !account;
  element("change-password").hidden = !account || account.google_only || account.key_only;
  element("attach-human-key-panel").hidden = !["user", "member"].includes(account?.role) || account.has_private_key;
  element("google-option").hidden = Boolean(account) || !libraryData.google_available;
  const username = element("account-username");
  username.hidden = !account;
  username.textContent = account ? `Username: ${account.username}` : "";
  element("key-panel").hidden = !account;
  element("ai-registration-panel").hidden = account?.role !== "user";
  const email = element("account-email");
  email.hidden = !account?.email;
  email.textContent = account?.email || "";
  element("comment-sign-in").hidden = Boolean(account);
  commentForm.hidden = !account;
  element("comment-author-choice").hidden = !["user", "member"].includes(account?.role);
  element("pdf-sign-in").hidden = Boolean(account);
  element("pdf-import").hidden = !account;
  element("create-group").hidden = account?.role !== "user";
  element("paper-group-filter").closest("label").hidden = account?.role !== "user";
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
  return paperDetails?.paper;
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

const pdfPattern = /^\/papers\/[1-9]\d*\/source\.pdf(?:#page=[1-9]\d*)?$/;

function closePdf(area) {
  element(`${area}-pdf-viewer`).hidden = true;
  element(`${area}-pdf-frame`).removeAttribute("src");
  element(`${area}-pdf-tab`).removeAttribute("href");
}

function viewPdf(area, url, label) {
  if (!pdfPattern.test(url)) return;
  const viewer = element(`${area}-pdf-viewer`);
  const disclosure = viewer.closest("details");
  if (disclosure) disclosure.open = true;
  element(`${area}-pdf-title`).textContent = label;
  element(`${area}-pdf-tab`).href = url;
  const frame = element(`${area}-pdf-frame`);
  if (frame.getAttribute("src") !== url) frame.src = url;
  viewer.hidden = false;
  viewer.scrollIntoView({ block: "nearest" });
}

function inlinePdfLink(link, area, url, label) {
  link.href = url;
  link.addEventListener("click", event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    viewPdf(area, url, label);
  });
}

for (const area of ["paper", "document"]) {
  element(`${area}-pdf-close`).addEventListener("click", () => closePdf(area));
}
element("view-paper-pdf").addEventListener("click", () => {
  const paper = selectedPaper();
  if (paper?.has_pdf) viewPdf("paper", paperPDFURL(paper.id), paper.title || paperFilename(paper));
});

function showPaper() {
  const selected = selectedPaper();
  const viewer = element("paper-pdf-viewer");
  const selectedId = selected ? String(selected.id) : "";
  if (viewer.dataset.paper !== selectedId) closePdf("paper");
  viewer.dataset.paper = selectedId;
  paperPicker.title = selected ? selected.title || selected.path : "";
  element("paper-detail").hidden = !selected;
  resetPaperMetrics(selected);
  lookupResults.replaceChildren();
  lookupForm.reset();
  if (!selected) return;
  element("paper-file-name").textContent = selected.has_pdf
    ? paperFilename(selected)
    : "No PDF attached. Use the PDF import to add the source file.";
  element("paper-file-links").hidden = !selected.has_pdf;
  const pdfURL = paperPDFURL(selected.id);
  element("open-paper-pdf").href = pdfURL;
  element("download-paper-pdf").href = `${pdfURL}?download=1`;
  const ownsPaper = selected.owner_id === libraryData.account?.id;
  const canManage = selected.owner_id === null || ownsPaper;
  element("detect-paper-metrics").hidden = !canManage || !selected.has_pdf;
  element("archive-paper").hidden = !canManage;
  element("membership").closest("details").hidden = !canManage || libraryData.account?.role !== "user";
  lookupPaperForm.hidden = !canManage || libraryData.account?.role !== "user";
  lookupForm.closest("details").hidden = !canManage;
  metadataForm.hidden = !canManage;
  element("paper-audience").textContent = selected.audience
    ? audienceLabels[selected.audience]
    : "Trusted human accounts (uploaded before access controls).";
  paperAccessForm.hidden = !ownsPaper;
  if (ownsPaper) {
    selectAudience(paperAccessForm.elements.audience, selected.audience);
    paperAccessForm.elements.allow_title.checked = Boolean(selected.allow_title);
    paperAccessForm.elements.recipients.value = (selected.recipients || []).join(", ");
  }

  const draft = commentDrafts.get(selected.id);
  newComment.value = draft?.body || "";
  commentForm.elements.kind.value = draft?.kind || "user";
  commentForm.elements.doi_refs.value = draft?.doiRefs || "";
  commentForm.elements.audience.value = draft?.audience || "owner";
  commentForm.elements.recipients.value = draft?.recipients || "";
  showPaperTargets(draft?.target, draft?.targetLabel);
  commentForm.elements.position.value = draft?.position || "";
  showPositionField();
  showReplyTarget(draft?.parentId);
  showSavedMetadata(selected);
  setMetadata(selected);
  lookupForm.elements.query.value = selected.doi;
  const memberships = new Set(paperDetails.group_ids);
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

  renderPaperComments(selected);
  if (paperComments.open) loadPaperTargets();
}

function renderPaperComments(selected) {
  renderComments(element("comments"), element("comment-summary"),
    libraryData.comments.filter(item => item.paper_id === selected.id),
    { paper_id: selected.id }, "paper", libraryStatus, comment => {
      rememberCommentDraft(comment.id);
      showReplyTarget(comment.id);
      newComment.focus();
    });
}

function renderComments(comments, summary, items, host, area, status, onReply) {
  comments.replaceChildren();
  summary.textContent = `Comments (${items.length})`;
  if (!items.length) add(comments, "p", "No comments yet.");
  const replies = new Map();
  for (const comment of items) {
    const siblings = replies.get(comment.parent_id) || [];
    siblings.push(comment);
    replies.set(comment.parent_id, siblings);
  }
  const pending = [...(replies.get(null) || [])].reverse();
  while (pending.length) {
    const comment = pending.pop();
    const children = replies.get(comment.id) || [];
    pending.push(...[...children].reverse());
    const article = add(comments, "article", undefined, comment.parent_id ? "paper-comment reply" : "paper-comment");
    article.id = `comment-${comment.id}`;
    if (comment.parent_id) add(article, "a", "In reply to parent comment").href = `#comment-${comment.parent_id}`;
    if (comment.deleted) {
      add(article, "p", "Deleted comment");
      continue;
    }
    let author = comment.author_name || "Unknown author";
    if (["local", "cloud"].includes(comment.author_role)) author += ` (${roleLabels[comment.author_role]})`;
    else if (comment.author_kind === "ai") author = `AI · recorded by ${author}`;
    add(article, "strong", author);
    add(article, "p", `Updated ${comment.updated} UTC · ${audienceLabels[comment.audience] || "Item access"}`, "comment-time");
    if (comment.finding_id) {
      add(article, "a", `Finding #${comment.finding_id}`).href =
        `/documents?document=${comment.document_id}&finding=${comment.finding_id}`;
    }
    if (comment.goal_id) {
      add(article, "a", `Goal #${comment.goal_id}`).href =
        `/documents?document=${comment.document_id}&goal=${comment.goal_id}`;
    }
    if (comment.target_kind === "pdf") {
      const label = `PDF page ${comment.target_position}`;
      inlinePdfLink(add(article, "a", label), area,
        `${paperPDFURL(comment.target_id)}#page=${comment.target_position}`, label);
    } else if (comment.target_kind === "document") {
      add(article, "a", `Document line ${comment.target_position}`).href =
        `/documents?document=${comment.target_id}&line=${comment.target_position}`;
    }
    if (comment.doi_refs.length) {
      const references = add(article, "ul", undefined, "doi-references");
      for (const doi of comment.doi_refs) {
        const link = add(add(references, "li"), "a", doi);
        link.href = doiURL(doi);
      }
    }
    if (libraryData.account) {
      const reply = add(article, "button", "Reply", "secondary");
      reply.addEventListener("click", () => onReply(comment));
      const review = add(article, "button", "Review thread with AI", "secondary");
      review.addEventListener("click", () => openAgent("thread", comment.id, `Comment thread · #${comment.id}`));
    }
    if (!libraryData.account || comment.author_id !== libraryData.account.id) {
      add(article, "p", comment.body, "comment-body");
      continue;
    }
    const edit = add(article, "details");
    add(edit, "summary", "Edit comment");
    add(article, "p", comment.body, "comment-body");
    const form = add(edit, "form");
    const field = add(add(form, "label", "Comment text"), "textarea");
    field.value = comment.body;
    field.required = true;
    field.maxLength = 20000;
    const refs = add(add(form, "label", "Related papers, one DOI or DOI link per line"), "textarea");
    refs.value = comment.doi_refs.join("\n");
    refs.maxLength = 9000;
    refs.rows = 2;
    const access = add(add(form, "label", "Comment access"), "select");
    fillAudiences(access, comment.audience || "inherit");
    const recipients = add(add(form, "label", "Share with usernames"), "input");
    recipients.maxLength = 1700;
    recipients.value = (comment.recipients || []).join(", ");
    enhanceRecipients(recipients);
    add(form, "button", "Save comment");
    const remove = add(form, "button", "Delete comment", "secondary");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!confirm("Delete this comment?")) return;
      remove.disabled = true;
      try {
        await updateLibrary("delete-comment", {
          ...host, comment_id: comment.id,
        }, "Comment deleted.", status);
      } catch (error) {
        status.textContent = error.message;
      } finally {
        remove.disabled = false;
      }
    });
    submit(form, () => updateLibrary("comments", {
      ...host, comment_id: comment.id, body: field.value, doi_refs: doiLines(refs.value),
      audience: access.value === "inherit" ? undefined : access.value,
      recipients: recipientNames(recipients.value),
    }, "Comment updated.", status), status);
  }
}

function showArchive(papers) {
  const archive = element("archived-papers");
  archive.replaceChildren();
  element("archive-summary").textContent = `Archived papers (${papers.length})`;
  if (!papers.length) add(archive, "p", "No archived papers.");
  for (const paper of papers) {
    const form = add(archive, "form", undefined, "archive-row");
    add(form, "span", paper.title || paperFilename(paper));
    add(form, "button", "Restore", "secondary");
    submit(form, async () => {
      await api("archive-paper", { paper_id: paper.id, archived: false });
      await loadLibrary(paper.id);
      libraryStatus.textContent = "Paper restored.";
    });
  }
}

function rememberPaperSelection() {
  const url = new URL(location.href);
  if ((url.searchParams.get("paper") || "") !== paperSelection) url.searchParams.delete("page");
  if (paperSelection) url.searchParams.set("paper", paperSelection);
  else url.searchParams.delete("paper");
  history.replaceState(null, "", url);
}

function paperFilename(item) {
  return item.path.split(/[\\/]/).pop();
}

function readPaperFilters() {
  const query = paperSearch.value.trim();
  const group = paperGroupFilter.value;
  const publisher = paperPublisherFilter.value;
  const fromYear = paperYearFrom.value ? String(paperYearFrom.valueAsNumber) : "";
  const throughYear = paperYearTo.value ? String(paperYearTo.valueAsNumber) : "";
  const invalidYears = !paperYearFrom.validity.valid || !paperYearTo.validity.valid
    || (fromYear && throughYear && Number(fromYear) > Number(throughYear));
  return {query, group, publisher, fromYear, throughYear, invalidYears};
}

function renderPaperOptions() {
  const papers = paperCatalog?.papers || [];
  const options = papers.map(item => [item.id, item.title || paperFilename(item)]);
  const selected = selectedPaper();
  if (paperSelection && !papers.some(item => String(item.id) === paperSelection)) {
    const label = selected ? selected.title || paperFilename(selected) : "Selected paper";
    options.unshift([paperSelection, `${label} (selected)`]);
  }
  setOptions(paperPicker, options, papers.length || !paperCatalog ? "Choose a paper" : "No matching papers");
  paperPicker.value = paperSelection;
}

function renderPaperPage(result, filters) {
  paperCatalog = result;
  paperPage = result.page;
  const pages = Math.max(1, Math.ceil(result.count / paperPageSize));
  element("paper-page-status").textContent = `Page ${paperPage} of ${pages}`;
  element("paper-page-previous").disabled = paperPage === 1;
  element("paper-page-next").disabled = paperPage >= pages;
  const {query, group, publisher, fromYear, throughYear, invalidYears} = filters;
  element("paper-search-status").textContent = invalidYears ? "Enter a valid publication year range."
    : query || group || publisher || fromYear || throughYear
      ? `${result.count} of ${result.total} papers match.` : "";
  renderPaperOptions();
}

function paperCatalogLoading() {
  element("paper-page-previous").disabled = true;
  element("paper-page-next").disabled = true;
  element("paper-catalog-retry").hidden = true;
  element("paper-search-status").textContent = "Loading papers…";
}

async function loadPaperCatalog(facets = false) {
  const sequence = ++paperCatalogSequence;
  const filters = readPaperFilters();
  const {query, group, publisher, fromYear, throughYear, invalidYears} = filters;
  paperCatalogLoading();
  if (invalidYears && !facets) {
    renderPaperPage({...paperCatalog, papers: [], count: 0, page: 1}, filters);
    return true;
  }
  const params = new URLSearchParams({page: String(paperPage)});
  for (const [key, value] of Object.entries({
    q: query, group, publisher, from_year: invalidYears ? "" : fromYear,
    through_year: invalidYears ? "" : throughYear, facets: facets ? "1" : "",
  })) {
    if (value) params.set(key, value);
  }
  try {
    const result = await api(`paper-catalog?${params}`);
    if (sequence !== paperCatalogSequence) return false;
    if (facets) {
      if (libraryData?.account?.id !== result.account?.id) commentDrafts.clear();
      libraryData = {account: result.account, google_available: result.google_available, groups: result.groups, comments: []};
      showAccount();
      setOptions(paperPublisherFilter, result.publishers.map(name => [name, name]), "All publishers");
      setOptions(paperGroupFilter, result.groups.map(item => [item.id, item.name]), "All groups");
      if (publisher !== paperPublisherFilter.value || group !== paperGroupFilter.value) {
        paperPage = 1;
        return loadPaperCatalog();
      }
    }
    renderPaperPage(invalidYears ? {...result, papers: [], count: 0, page: 1} : result, filters);
    return true;
  } catch (error) {
    if (sequence !== paperCatalogSequence) return false;
    element("paper-search-status").textContent = error.message;
    element("paper-catalog-retry").hidden = false;
    return false;
  }
}

function refreshPaperFilters(debounce = false) {
  if (!paperCatalog) return;
  clearTimeout(paperCatalogTimer);
  paperPage = 1;
  if (!debounce) return loadPaperCatalog();
  ++paperCatalogSequence;
  paperCatalogLoading();
  paperCatalogTimer = setTimeout(() => loadPaperCatalog(), 250);
}

async function loadSelectedPaper() {
  const sequence = ++paperSelectionSequence;
  ++lookupSequence;
  const id = paperSelection;
  paperDetails = null;
  element("paper-detail").hidden = true;
  const status = element("paper-detail-status");
  const retry = element("paper-detail-retry");
  status.textContent = "";
  retry.hidden = true;
  if (element("paper-pdf-viewer").dataset.paper !== id) closePdf("paper");
  if (!id) return;

  status.textContent = "Loading paper…";
  try {
    const result = await api(`paper-detail?paper_id=${encodeURIComponent(id)}`);
    if (sequence !== paperSelectionSequence) return;
    paperDetails = result;
    libraryData.comments = [];
    nextCommentBefore = null;
    element("older-comments").hidden = true;
    status.textContent = "";
    renderPaperOptions();
    showPaper();

    const params = new URLSearchParams(location.search);
    const requestedPage = Number(params.get("page"));
    const selected = result.paper;
    if (params.get("paper") === id && selected.has_pdf && Number.isSafeInteger(requestedPage)
        && requestedPage > 0 && element("paper-pdf-viewer").hidden) {
      viewPdf("paper", `${paperPDFURL(selected.id)}#page=${requestedPage}`, selected.title || paperFilename(selected));
    }
    await loadPaperComments();
  } catch (error) {
    if (sequence !== paperSelectionSequence) return;
    status.textContent = error.message;
    if (error.status === 404 || error.status === 400) {
      paperSelection = "";
      rememberPaperSelection();
      renderPaperOptions();
    } else {
      retry.hidden = false;
    }
  }
}

function showPaperTargets(target = "", label = "") {
  const options = [...(paperTargets || [])];
  if (target && !paperTargets?.has(target)) {
    const title = label || (paperTargets ? target : "Selected location");
    const unavailable = paperTargets && !title.endsWith(" (unavailable)");
    options.unshift([target, unavailable ? `${title} (unavailable)` : title]);
  }
  setOptions(commentForm.elements.target, options, "No location");
  commentForm.elements.target.value = target;
  showPositionField();
}

function loadPaperTargets() {
  if (paperTargetRequest || !libraryData?.account) return paperTargetRequest;
  const revision = paperLibraryRevision;
  const status = element("paper-targets-status");
  const retry = element("paper-targets-retry");
  status.textContent = "Loading locations…";
  retry.hidden = true;
  paperTargetRequest = api("paper-comment-targets").then(result => {
    if (revision !== paperLibraryRevision) return;
    paperTargets = new Map([
      ...result.papers.map(paper => [`pdf:${paper.id}`, `PDF · ${paper.title || paperFilename(paper)}`]),
      ...result.documents.map(doc => [`document:${doc.id}`, `Document · ${doc.title}`]),
    ]);
    const field = commentForm.elements.target;
    if (selectedPaper()) showPaperTargets(field.value, field.selectedOptions[0]?.textContent);
    status.textContent = "";
  }).catch(error => {
    if (revision !== paperLibraryRevision) return;
    paperTargetRequest = null;
    status.textContent = error.message;
    retry.hidden = false;
  });
  return paperTargetRequest;
}

function loadPaperArchive() {
  if (paperArchiveRequest) return paperArchiveRequest;
  const revision = paperLibraryRevision;
  const status = element("paper-archive-status");
  const retry = element("paper-archive-retry");
  status.textContent = "Loading archived papers…";
  retry.hidden = true;
  paperArchiveRequest = api("paper-archive").then(result => {
    if (revision !== paperLibraryRevision) return;
    showArchive(result.papers);
    status.textContent = "";
  }).catch(error => {
    if (revision !== paperLibraryRevision) return;
    paperArchiveRequest = null;
    status.textContent = error.message;
    retry.hidden = false;
  });
  return paperArchiveRequest;
}

const paperFilters = [paperSearch, paperGroupFilter, paperPublisherFilter, paperYearFrom, paperYearTo];

async function loadPapersPage(paperId) {
  const revision = ++paperLibraryRevision;
  ++paperSelectionSequence;
  ++commentLoadSequence;
  ++lookupSequence;
  clearTimeout(paperCatalogTimer);
  paperCatalog = null;
  paperDetails = null;
  paperTargets = paperTargetRequest = paperArchiveRequest = null;
  paperSelection = paperId === undefined
    ? new URLSearchParams(location.search).get("paper") || "" : String(paperId);
  if (paperId !== undefined) rememberPaperSelection();
  element("paper-detail").hidden = true;
  element("paper-detail-status").textContent = "";
  element("paper-detail-retry").hidden = true;
  element("archived-papers").replaceChildren();
  element("archive-summary").textContent = "Archived papers";
  for (const item of ["paper-targets", "paper-archive"]) {
    element(`${item}-status`).textContent = "";
    element(`${item}-retry`).hidden = true;
  }
  for (const control of [...paperFilters, paperPicker]) control.disabled = true;
  renderPaperOptions();
  if (!await loadPaperCatalog(true) || revision !== paperLibraryRevision) return;
  for (const control of [...paperFilters, paperPicker]) control.disabled = false;
  await Promise.all([loadSelectedPaper(), paperArchive.open ? loadPaperArchive() : null]);
}

async function loadLibrary(paperId) {
  const previousAccount = libraryData?.account?.id;
  if (papersPage) return loadPapersPage(paperId);
  const route = accountPage ? "account" : documentsPage ? "documents?comments=none&content=summary" : "compare";
  libraryData = await api(route);
  if (accountPage) {
    if (previousAccount !== libraryData.account?.id) {
      element("ai-invitation-prompt").value = "";
      element("ai-invitation-result").hidden = true;
    }
    showAccount();
    showKeys();
    return;
  }
  if (documentsPage) {
    await showDocuments(libraryData.account?.id !== previousAccount);
    if (previousAccount === undefined) await openRequestedDocument();
    await loadDocumentComments();
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
  if (!rawMetrics.length) {
    status.textContent = libraryData.account ? "No metrics are available to this account." : "";
    if (!libraryData.account) add(status, "a", "Sign in to see available metrics").href = "/account";
  }
}

async function loadPaperComments() {
  const sequence = ++commentLoadSequence;
  const data = libraryData;
  const selected = selectedPaper();
  if (!selected) return;
  const isCurrent = () =>
    sequence === commentLoadSequence && data === libraryData && selectedPaper()?.id === selected.id;
  const status = element("paper-comments-status");
  const retry = element("paper-comments-retry");
  commentForm.hidden = true;
  status.textContent = "Loading comments…";
  retry.hidden = true;
  try {
    const result = await api(`paper-comments?paper_id=${selected.id}`);
    if (!isCurrent()) return;
    data.comments = result.comments;
    nextCommentBefore = result.next_before;
    element("older-comments").hidden = !nextCommentBefore;
    status.textContent = "";
    commentForm.hidden = !data.account;
    renderPaperComments(selected);
    showReplyTarget(commentDrafts.get(selected.id)?.parentId);
  } catch (error) {
    if (!isCurrent()) return;
    status.textContent = error.message;
    retry.hidden = false;
  }
}

element("older-comments").addEventListener("click", async event => {
  const button = event.currentTarget;
  const sequence = commentLoadSequence;
  const data = libraryData;
  const selected = selectedPaper();
  const cursor = nextCommentBefore;
  if (!selected || !cursor) return;
  button.disabled = true;
  try {
    const result = await api(`paper-comments?paper_id=${selected.id}&before=${cursor}`);
    if (sequence !== commentLoadSequence || data !== libraryData || selectedPaper()?.id !== selected.id) return;
    data.comments = [...result.comments, ...data.comments];
    nextCommentBefore = result.next_before;
    button.hidden = !nextCommentBefore;
    renderPaperComments(selected);
  } catch (error) {
    if (sequence === commentLoadSequence && data === libraryData && selectedPaper()?.id === selected.id) {
      libraryStatus.textContent = error.message;
    }
  } finally {
    button.disabled = false;
  }
});

async function updateLibrary(route, data, message, status = libraryStatus) {
  await api(route, data);
  await loadLibrary();
  status.textContent = message;
}

function submit(form, action, status = libraryStatus) {
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (form.dataset.busy) return;
    form.dataset.busy = "true";
    try {
      await action(event);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      delete form.dataset.busy;
    }
  });
}

paperSearch.addEventListener("input", () => refreshPaperFilters(true));
for (const field of [paperPublisherFilter, paperGroupFilter]) {
  field.addEventListener("change", () => refreshPaperFilters());
}
for (const field of [paperYearFrom, paperYearTo]) {
  field.addEventListener("input", () => refreshPaperFilters());
}
element("paper-page-previous").addEventListener("click", () => { paperPage--; return loadPaperCatalog(); });
element("paper-page-next").addEventListener("click", () => { paperPage++; return loadPaperCatalog(); });
paperPicker.addEventListener("change", () => {
  libraryStatus.textContent = "";
  paperSelection = paperPicker.value;
  rememberPaperSelection();
  return loadSelectedPaper();
});
element("paper-catalog-retry").addEventListener("click", () => paperCatalog ? loadPaperCatalog() : loadPapersPage());
element("paper-detail-retry").addEventListener("click", loadSelectedPaper);
element("paper-comments-retry").addEventListener("click", loadPaperComments);
element("paper-targets-retry").addEventListener("click", loadPaperTargets);
element("paper-archive-retry").addEventListener("click", loadPaperArchive);
paperComments.addEventListener("toggle", () => { if (paperComments.open && selectedPaper()) return loadPaperTargets(); });
paperArchive.addEventListener("toggle", () => { if (paperArchive.open && paperCatalog) return loadPaperArchive(); });
groupPicker.addEventListener("change", filterGroups);
metadataForm.addEventListener("input", () => {
  metadataSource = "Manual";
  element("metadata-source").textContent = "Source: Manual";
});

function metricKeywords(value) {
  return value.split(/[,\n]/).map(phrase => phrase.trim()).filter(Boolean);
}

async function importPaper(file, audience, recipients, keywords) {
  const response = await fetch("/api/papers", {
    method: "POST",
    headers: {
      "Content-Type": "application/pdf",
      "X-Paper-Filename": encodeURIComponent(file.name),
      "X-Paper-Audience": audience,
      "X-Paper-Recipients": encodeURIComponent(JSON.stringify(recipients)),
      "X-Paper-Metric-Keywords": encodeURIComponent(JSON.stringify(keywords)),
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
  const upload = element("pdf-import").elements;
  const audience = upload.audience.value;
  const recipients = recipientNames(upload.recipients.value);
  const keywords = metricKeywords(upload.metric_keywords.value);
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
        const imported = await importPaper(file, audience, recipients, keywords);
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
submit(accountForm, async () => {
  accountStatus.textContent = "";
  try {
    await api("sign-in", {
      username: accountForm.elements.username.value,
      password: accountForm.elements.password.value,
    });
    accountForm.reset();
    notifySessionChange();
    await loadLibrary();
    accountStatus.textContent = "Signed in.";
  } catch (error) {
    accountStatus.textContent = error.message;
  }
});
submit(element("sign-out"), async () => {
  try {
    await api("sign-out", {});
    notifySessionChange();
    await loadLibrary();
    accountStatus.textContent = "Signed out.";
  } catch (error) {
    accountStatus.textContent = error.message;
  }
});
const signupForm = element("signup");
submit(signupForm, async () => {
  try {
    await api("register", Object.fromEntries(new FormData(signupForm)));
    signupForm.reset();
    notifySessionChange();
    await loadLibrary();
    accountStatus.textContent = "Account created.";
  } catch (error) {
    accountStatus.textContent = error.message;
  }
});

const createKeyForm = element("create-key");
const issuedKey = element("issued-key");
const aiInvitationForm = element("create-ai-invitation");
const aiInvitationPrompt = element("ai-invitation-prompt");

submit(aiInvitationForm, async () => {
  const accountId = libraryData.account?.id;
  aiInvitationPrompt.value = "";
  element("ai-invitation-result").hidden = true;
  const {registration_path, registration_url, username, role} = await api("ai/invitations", Object.fromEntries(new FormData(aiInvitationForm)));
  if (libraryData.account?.id !== accountId) return;
  const identity = `~/.paper-library/${username}.json`;
  const client = "python3 -m paper_client.agent";
  aiInvitationPrompt.value = `Connect to my Paper Library as ${username} (${role} AI). Register this agent and verify the connection.

One-time registration URL (expires in 15 minutes):
${registration_url}

From the Paper Library repository, install the client with python3 -m pip install ./paper_client, then run:
${client} register --username ${username} --identity ${identity}

Supply the registration URL when prompted, or pass it privately on stdin. This command generates and saves an Ed25519 private key in the identity file. Keep the key and any access tokens out of chat and logs. Verify the account and read the usage guide:
${client} request --identity ${identity} /api/account
${client} request --identity ${identity} /api/skills/default

If you use your own HTTP client, send POST bodies as JSON with Content-Type: application/json. Generate and store an Ed25519 key and sign paper-library:register:${username}:${registration_path} as ASCII. POST public_key and signature as unpadded base64url to the registration URL. Then POST {"username":"${username}"} to /api/ai/challenge, sign paper-library:login:${username}:<challenge> as ASCII, and POST username, challenge, and base64url signature to /api/ai/login. Use the returned access_token as a Bearer token. Verify the role with /api/account. The API contract is at /api/openapi.json.

Use the HTTPS URL as provided. If the library uses loopback on another machine, use its forwarded loopback port and keep the registration path. Report the connected username and role.`;
  element("ai-invitation-result").hidden = false;
  accountStatus.textContent = "";
}, accountStatus);

element("copy-ai-invitation").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(aiInvitationPrompt.value);
    accountStatus.textContent = "Registration prompt copied.";
  } catch {
    aiInvitationPrompt.select();
    accountStatus.textContent = "Copy the selected registration prompt.";
  }
});

function showKeys() {
  const list = element("application-key-list");
  list.replaceChildren();
  if (!libraryData.account) {
    issuedKey.value = "";
    element("issued-key-label").hidden = true;
    return;
  }
  for (const key of libraryData.keys || []) {
    const form = add(list, "form", undefined, "archive-row");
    add(form, "span", `${key.label} · ${key.created} UTC`);
    add(form, "button", "Revoke", "secondary");
    submit(form, async () => {
      try {
        await api("revoke-key", { key_id: key.id });
        issuedKey.value = "";
        element("issued-key-label").hidden = true;
        await loadLibrary();
        accountStatus.textContent = "Key revoked.";
      } catch (error) {
        accountStatus.textContent = error.message;
      }
    });
  }
}

submit(createKeyForm, async () => {
  try {
    const result = await api("application-keys", { label: createKeyForm.elements.label.value });
    createKeyForm.reset();
    await loadLibrary();
    issuedKey.value = result.key;
    element("issued-key-label").hidden = false;
    issuedKey.select();
  } catch (error) {
    accountStatus.textContent = error.message;
  }
});

const passwordForm = element("change-password");
submit(passwordForm, async () => {
  try {
    await api("change-password", {
      current_password: passwordForm.elements.current_password.value,
      new_password: passwordForm.elements.new_password.value,
    });
    passwordForm.reset();
    notifySessionChange();
    await loadLibrary();
    accountStatus.textContent = "Password changed and application keys revoked. Sign in again."
  } catch (error) {
    accountStatus.textContent = error.message;
  }
});

function notifySessionChange() {
  try { localStorage.setItem("paper-session-change", String(Date.now())); } catch {}
}
addEventListener("storage", event => {
  if (event.key === "paper-session-change") location.reload();
});
addEventListener("pageshow", event => {
  if (event.persisted) location.reload();
});

function recipientNames(value) {
  return value.split(/[\s,]+/).filter(Boolean);
}

function doiLines(value) {
  return value.split("\n").map(line => line.trim()).filter(Boolean);
}

function doiURL(doi) {
  return `https://doi.org/${doi.split("/").map(encodeURIComponent).join("/")}`;
}

function showReplyTarget(parentId) {
  const parent = libraryData.comments.find(comment => comment.id === parentId);
  const context = element("reply-context");
  context.hidden = !parent;
  element("cancel-reply").hidden = !parent;
  element("post-comment").textContent = parent ? "Post reply" : "Add comment";
  context.textContent = parent ? `Replying to ${parent.author_name || "an unknown author"}` : "";
}

function showPositionField() {
  const field = commentForm.elements.target;
  const target = field.value;
  const unavailable = target && paperTargets && !paperTargets.has(target);
  field.setCustomValidity(unavailable ? "Choose an available location or clear it." : "");
  element("comment-position-label").hidden = !target;
  commentForm.elements.position.required = Boolean(target);
  element("comment-position-text").textContent = target.startsWith("pdf:") ? "PDF page" : "Document line";
}

function rememberCommentDraft(parentId) {
  const id = selectedPaper().id;
  commentDrafts.set(id, {
    body: newComment.value, kind: commentForm.elements.kind.value,
    doiRefs: commentForm.elements.doi_refs.value, audience: commentForm.elements.audience.value, parentId,
    target: commentForm.elements.target.value,
    targetLabel: commentForm.elements.target.selectedOptions[0]?.textContent,
    position: commentForm.elements.position.value,
    recipients: commentForm.elements.recipients.value,
  });
}

element("cancel-reply").addEventListener("click", () => {
  rememberCommentDraft(null);
  showReplyTarget(null);
  newComment.focus();
});
commentForm.addEventListener("input", () => {
  showPositionField();
  rememberCommentDraft(commentDrafts.get(selectedPaper().id)?.parentId);
});
submit(commentForm, async () => {
  const paperId = selectedPaper().id;
  const draft = commentDrafts.get(paperId);
  const parentId = libraryData.comments.some(comment => comment.id === draft?.parentId) ? draft.parentId : null;
  const [kind, id] = commentForm.elements.target.value.split(":");
  const location = kind ? { kind, id: Number(id), position: Number(commentForm.elements.position.value) } : null;
  await api("comments", {
    location, paper_id: paperId, body: newComment.value, kind: commentForm.elements.kind.value,
    doi_refs: doiLines(commentForm.elements.doi_refs.value), parent_id: parentId,
    audience: commentForm.elements.audience.value,
    recipients: recipientNames(commentForm.elements.recipients.value),
  });
  if (commentDrafts.get(paperId) === draft) commentDrafts.delete(paperId);
  await loadLibrary();
  libraryStatus.textContent = parentId ? "Reply added." : "Comment added.";
});
submit(paperAccessForm, () => updateLibrary("paper-access", {
  paper_id: selectedPaper().id, audience: paperAccessForm.elements.audience.value,
  allow_title: paperAccessForm.elements.allow_title.checked,
  recipients: recipientNames(paperAccessForm.elements.recipients.value),
}, "File access updated."));
submit(element("archive-paper"), async () => {
  const {id} = selectedPaper();
  await api("archive-paper", { paper_id: id, archived: true });
  if (paperSelection === String(id)) {
    paperSelection = "";
    rememberPaperSelection();
  }
  await loadLibrary();
  libraryStatus.textContent = "Paper archived.";
});
submit(metadataForm, () => updateLibrary("metadata", {
  ...Object.fromEntries(metadataFields.map(key => [key, metadataForm.elements[key].value.trim()])),
  paper_id: selectedPaper().id,
  source: metadataSource || "Manual",
}, "Metadata saved."));
function groupCrossrefResults(container, matches, renderItem) {
  const groups = new Map();
  for (const match of matches) {
    const publisher = match.publisher || "Unknown publisher";
    const venue = match.venue_group || match.venue || "Unknown venue";
    if (!groups.has(publisher)) groups.set(publisher, new Map());
    const venues = groups.get(publisher);
    if (!venues.has(venue)) venues.set(venue, []);
    venues.get(venue).push(match);
  }
  const alphabetical = ([a], [b]) => a.localeCompare(b);
  for (const [publisher, venues] of [...groups].sort(alphabetical)) {
    add(container, "h3", publisher);
    for (const [venue, papers] of [...venues].sort(alphabetical)) {
      add(container, "h4", venue);
      const list = add(container, "ol");
      papers.sort((a, b) => (Number(b.year) || 0) - (Number(a.year) || 0) || a.title.localeCompare(b.title));
      for (const paper of papers) renderItem(add(list, "li"), paper);
    }
  }
}

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
  groupCrossrefResults(lookupResults, matches, (item, match) => {
    const label = [match.title, match.authors, match.year, match.venue, match.doi].filter(Boolean).join(" · ");
    const button = add(item, "button", label || "Untitled result");
    button.type = "button";
    button.addEventListener("click", () => {
      setMetadata(match);
      libraryStatus.textContent = "Result selected. Save metadata to update this paper.";
    });
  });
}

submit(lookupPaperForm, () => findMetadata({ paper_id: selectedPaper().id }));
submit(lookupForm, () => findMetadata({
  kind: lookupForm.elements.kind.value, query: lookupForm.elements.query.value,
}));

const relatedSearch = element("related-paper-search");
const crossrefPublishers = new Set();
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
      publisher: relatedSearch.elements.publisher.value.trim(),
      year_from: relatedSearch.elements.year_from.value,
      year_to: relatedSearch.elements.year_to.value,
    });
    for (const match of matches) if (match.publisher) crossrefPublishers.add(match.publisher);
    const datalist = element("crossref-publishers");
    datalist.replaceChildren();
    for (const publisher of [...crossrefPublishers].sort()) add(datalist, "option").value = publisher;
    groupCrossrefResults(results, matches, (item, { title, doi, year }) => {
      item.append(`${year || "Year unknown"} · ${title} · `);
      add(item, "a", doi).href = doiURL(doi);
    });
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

let suggestionIndex = 0;

function enhanceRecipients(input) {
  const label = input.closest("label");
  const field = document.createElement("div");
  field.className = "recipient-field";
  label.before(field);
  field.append(label);
  const options = add(field, "div", undefined, "recipient-options");
  options.id = `recipient-options-${++suggestionIndex}`;
  options.hidden = true;
  options.setAttribute("role", "listbox");
  options.setAttribute("aria-label", "Matching usernames");
  input.autocomplete = "off";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", options.id);
  let sequence = 0;
  let timeout;
  let inserting = false;

  function hide() {
    sequence++;
    clearTimeout(timeout);
    options.replaceChildren();
    options.hidden = true;
    input.setAttribute("aria-expanded", "false");
  }

  input.addEventListener("input", () => {
    if (inserting) return;
    hide();
    const pivot = input.selectionStart ?? input.value.length;
    const first = input.value.lastIndexOf(",", pivot - 1) + 1;
    const comma = input.value.indexOf(",", pivot);
    const last = comma < 0 ? input.value.length : comma;
    const query = input.value.slice(first, last).trim();
    if (query.length < 2) return;
    const baseValue = input.value;
    const request = sequence;
    timeout = setTimeout(async () => {
      let matches;
      try {
        matches = await api(`usernames?q=${encodeURIComponent(query)}`);
      } catch {
        return;
      }
      if (request !== sequence || input.value !== baseValue || !field.contains(document.activeElement)) return;
      for (const match of matches) {
        const text = match.display_name ? `${match.username} · ${match.display_name}` : match.username;
        const button = add(options, "button", text, "secondary");
        button.type = "button";
        button.setAttribute("role", "option");
        button.addEventListener("click", () => {
          const prefix = first ? " " : "";
          const suffix = comma < 0 ? ", " : "";
          input.setRangeText(prefix + match.username + suffix, first, last, "end");
          hide();
          input.focus();
          inserting = true;
          input.dispatchEvent(new Event("input", { bubbles: true }));
          inserting = false;
        });
      }
      options.hidden = !matches.length;
      input.setAttribute("aria-expanded", String(matches.length > 0));
    }, 180);
  });

  field.addEventListener("focusout", event => {
    if (!field.contains(event.relatedTarget)) hide();
  });
  field.addEventListener("keydown", event => {
    if (options.hidden) return;
    if (event.key === "Escape") {
      hide();
      input.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const choices = [...options.querySelectorAll("button")];
    const current = choices.indexOf(document.activeElement);
    const offset = event.key === "ArrowDown" ? 1 : -1;
    const next = current < 0 ? (offset > 0 ? 0 : choices.length - 1) : (current + offset + choices.length) % choices.length;
    event.preventDefault();
    choices[next]?.focus();
  });
}
for (const field of document.querySelectorAll('input[name="recipients"]')) enhanceRecipients(field);

const agentDialog = element("agent-dialog");
const agentAccount = element("agent-username");
const agentAvailability = element("agent-availability");
const agentPosition = element("agent-position");
const agentPost = element("agent-post");
const agentSubmit = element("send-agent-review");
const agentStatus = element("agent-review-status");
const agentResult = element("agent-review-result");
let agentTarget;
let agentView = 0;
let agentPoll;
let agentPending = false;
const eligibleAgents = new Map();

function syncAgentChoice() {
  const selected = eligibleAgents.get(agentAccount.value);
  agentSubmit.disabled = agentPending || !selected;
  element("agent-cloud-note").hidden = selected?.role !== "cloud";
}

function showAgentReview(review, view) {
  const pending = review.status === "pending";
  agentPending = pending;
  syncAgentChoice();
  agentResult.hidden = pending;
  agentResult.textContent = pending ? "" : review.response;
  agentStatus.textContent = pending ? `Waiting for ${review.agent} to pick up review #${review.id}.`
    : review.status === "failed" ? "The AI account could not complete the review."
    : review.comment_id ? "Review complete. A private AI comment was posted." : "Review complete.";
  if (pending) {
    agentPoll = setTimeout(async () => {
      try {
        const data = await api(`reviews?id=${review.id}`);
        if (view === agentView) showAgentReview(data.review, view);
      } catch (error) {
        if (view !== agentView) return;
        agentStatus.textContent = error.message;
        agentPending = false;
        syncAgentChoice();
      }
    }, 3000);
  }
}

async function openAgent(kind, id, label, position = "") {
  if (!libraryData.account) {
    libraryStatus.textContent = "Sign in to request an AI review.";
    return;
  }
  const view = ++agentView;
  agentTarget = {kind, target_id: id};
  element("agent-target").textContent = label;
  element("agent-position-field").hidden = kind === "thread";
  element("agent-position-label").textContent = kind === "document" ? "Source line (optional)" : "PDF page";
  agentPosition.value = position || (kind === "paper" ? "1" : "");
  agentPost.checked = false;
  agentResult.hidden = true;
  agentResult.textContent = "";
  agentStatus.textContent = "";
  const previous = agentAccount.value;
  eligibleAgents.clear();
  agentAccount.replaceChildren();
  add(agentAccount, "option", "Choose an AI account").value = "";
  agentPending = false;
  syncAgentChoice();
  agentAvailability.textContent = "Checking eligible AI accounts…";
  agentDialog.showModal();
  try {
    const query = new URLSearchParams(agentTarget);
    const [data, availability] = await Promise.all([api(`reviews?${query}`), api(`review-agents?${query}`)]);
    if (view !== agentView) return;
    const latest = data.reviews[0];
    for (const agent of availability.agents) {
      eligibleAgents.set(agent.username, agent);
      const account = agent.display_name ? `${agent.display_name} (@${agent.username})` : agent.username;
      add(agentAccount, "option", `${account} · ${roleLabels[agent.role]}`).value = agent.username;
    }
    agentAccount.value = [latest?.agent, previous].find(username => eligibleAgents.has(username))
      ?? (availability.agents.length === 1 ? availability.agents[0].username : "");
    agentAvailability.textContent = availability.agents.length ? "" : "Share this item and its sources with an AI account to request a review.";
    if (latest) showAgentReview(latest, view);
    else syncAgentChoice();
  } catch (error) {
    if (view !== agentView) return;
    agentAvailability.textContent = error.message;
  }
}

agentAccount.addEventListener("change", syncAgentChoice);
agentDialog.addEventListener("close", () => {
  ++agentView;
  clearTimeout(agentPoll);
});
element("request-agent-review").addEventListener("submit", async event => {
  event.preventDefault();
  const agent = eligibleAgents.get(agentAccount.value);
  if (!agent || agentPending) return;
  const view = agentView;
  agentPending = true;
  syncAgentChoice();
  agentStatus.textContent = "Requesting review…";
  try {
    const data = await api("reviews", {
      action: "create", ...agentTarget,
      agent: agent.username,
      agent_role: agent.role,
      position: agentPosition.value ? agentPosition.valueAsNumber : null,
      post: agentPost.checked,
    });
    if (view === agentView) showAgentReview(data.review, view);
  } catch (error) {
    if (view !== agentView) return;
    agentStatus.textContent = error.message;
    agentPending = false;
    syncAgentChoice();
  }
});
element("review-paper").addEventListener("click", () => {
  const paper = selectedPaper();
  if (paper?.has_pdf) {
    const page = Number(new URLSearchParams(location.search).get("page")) || 1;
    openAgent("paper", paper.id, paper.title || paperFilename(paper), page);
  }
});
element("review-document").addEventListener("click", () => {
  const document = selectedDocument();
  if (document) openAgent("document", document.id, document.title);
});

const metricPanel = element("paper-metrics");
const metricState = element("metric-state");
const metricPicker = element("metric-correction-picker");
const metricStatus = element("metric-correction-status");
const metricForm = element("metric-correction-form");
const metricEditors = element("metric-editors-form");
const metricClaim = element("claim-metric-paper");
const metricMore = element("more-paper-metrics");
const metricHistory = element("metric-revisions");
const metricOlder = element("older-metric-revisions");
const metricFields = ["page", "metric", "value", "unit", "conditions", "evidence"];
let metricListing;
let metricHistoryBefore;
let metricHistoryRequest = 0;

function metricLabel(metric) {
  return `Page ${metric.page} · ${metric.metric} · ${metric.value} ${metric.unit}`.trim();
}

function metricDescription(metric) {
  return [metricLabel(metric), metric.conditions, metric.evidence].filter(Boolean).join("\n");
}

function resetPaperMetrics(paper) {
  const samePaper = paper?.id === metricListing?.paperId && libraryData.account?.id === metricListing?.accountId;
  if (!samePaper) {
    metricPanel.open = false;
    metricState.value = "0";
  }
  if (!metricPanel.open) metricListing = null;
  else reloadPaperMetrics();
}

function metricListingCurrent(listing) {
  return metricListing === listing && selectedPaper()?.id === listing.paperId;
}

async function listPaperMetrics(listing, append = false) {
  if (listing.loading) return;
  listing.loading = true;
  metricMore.disabled = true;
  metricStatus.textContent = "Loading metrics…";
  try {
    const cursor = append ? `&after=${listing.next}` : "";
    const scope = listing.removed ? "&removed=1" : "";
    const data = await api(`paper-metrics?paper_id=${listing.paperId}${scope}${cursor}`);
    if (!metricListingCurrent(listing)) return;
    for (const metric of data.metrics) {
      listing.records.set(String(metric.id), metric);
      add(metricPicker, "option", metricLabel(metric).slice(0, 180)).value = metric.id;
    }
    listing.next = data.next_after;
    metricMore.hidden = listing.next === null;
    metricClaim.hidden = !data.can_claim_paper;
    metricStatus.textContent = listing.records.size ? "" : listing.removed ? "No removed metrics." : "No active metrics.";
  } catch (error) {
    if (metricListingCurrent(listing)) metricStatus.textContent = error.message;
  } finally {
    listing.loading = false;
    if (metricListingCurrent(listing)) metricMore.disabled = false;
  }
}

function reloadPaperMetrics() {
  const paper = selectedPaper();
  if (!paper) return;
  metricPicker.replaceChildren();
  add(metricPicker, "option", "Choose a metric").value = "";
  element("metric-correction-detail").hidden = true;
  metricClaim.hidden = true;
  metricMore.hidden = true;
  metricListing = {paperId: paper.id, accountId: libraryData.account?.id, records: new Map(),
    next: null, removed: metricState.value === "1"};
  return listPaperMetrics(metricListing);
}

async function loadMetricHistory(listing, metric, append = false) {
  const request = ++metricHistoryRequest;
  metricOlder.disabled = true;
  try {
    const cursor = append ? `&before=${metricHistoryBefore}` : "";
    const data = await api(`metric-history?metric_id=${metric.id}${cursor}`);
    if (request !== metricHistoryRequest || !metricListingCurrent(listing)) return;
    if (!append) {
      metricHistory.replaceChildren();
      add(metricHistory, "p", `Original (revision 1)\n${metricDescription(data.original)}`, "comment-body");
      metricEditors.hidden = !data.editors;
      element("metric-editor-names").textContent = data.editors?.join(", ") || "No named editors.";
    }
    for (const record of data.corrections) {
      add(metricHistory, "p",
        `Revision ${record.revision}${record.removed ? " (removed)" : ""} · ${record.editor} · ${record.created} UTC\n${metricDescription(record)}\nReason: ${record.reason}`,
        "comment-body");
    }
    metricHistoryBefore = data.next_before;
    metricOlder.hidden = metricHistoryBefore === null;
  } catch (error) {
    if (request === metricHistoryRequest && metricListingCurrent(listing)) metricStatus.textContent = error.message;
  } finally {
    if (request === metricHistoryRequest && metricListingCurrent(listing)) metricOlder.disabled = false;
  }
}

function showPaperMetric() {
  ++metricHistoryRequest;
  const listing = metricListing;
  const metric = listing?.records.get(metricPicker.value);
  element("metric-correction-detail").hidden = !metric;
  if (!metric) return;
  element("metric-current").textContent = `${metricDescription(metric)}\nRevision ${metric.revision}${metric.removed ? " (removed)" : ""}`;
  metricForm.hidden = !metric.can_edit;
  element("metric-correction-fields").hidden = Boolean(metric.removed);
  element("metric-correction-fields").disabled = Boolean(metric.removed);
  element("save-metric-correction").hidden = Boolean(metric.removed);
  element("remove-metric").hidden = Boolean(metric.removed);
  element("restore-metric").hidden = !metric.removed;
  metricEditors.hidden = true;
  metricOlder.hidden = true;
  metricHistory.replaceChildren();
  for (const field of metricFields) metricForm.elements[field].value = metric[field];
  metricForm.elements.reason.value = "";
  return loadMetricHistory(listing, metric);
}

metricPanel.addEventListener("toggle", () => {
  if (metricPanel.open && !metricListing) reloadPaperMetrics();
});
metricPicker.addEventListener("change", () => {
  metricStatus.textContent = "";
  showPaperMetric();
});
element("reload-paper-metrics").addEventListener("click", reloadPaperMetrics);
metricState.addEventListener("change", reloadPaperMetrics);
metricMore.addEventListener("click", () => listPaperMetrics(metricListing, true));
metricOlder.addEventListener("click", () => {
  const metric = metricListing?.records.get(metricPicker.value);
  if (metric) loadMetricHistory(metricListing, metric, true);
});
submit(metricClaim, async () => {
  const listing = metricListing;
  await api("claim-paper", {paper_id: listing.paperId});
  if (metricListingCurrent(listing)) await loadSelectedPaper();
}, metricStatus);
submit(element("detect-paper-metrics"), async event => {
  const listing = metricListing;
  const {keywords} = event.currentTarget.elements;
  const data = await api("detect-paper-metrics", {paper_id: listing.paperId, keywords: metricKeywords(keywords.value)});
  if (!metricListingCurrent(listing)) return;
  await reloadPaperMetrics();
  if (selectedPaper()?.id === listing.paperId) {
    metricStatus.textContent = data.has_text ? `${data.metrics} matching metric candidate(s) processed.` : "The PDF has no extractable text.";
  }
}, metricStatus);
submit(metricForm, async event => {
  const listing = metricListing;
  const metric = listing.records.get(metricPicker.value);
  const action = event.submitter?.value || (metric.removed ? "restore" : "correct");
  const values = {};
  if (action === "correct") {
    for (const field of metricFields) {
      const input = metricForm.elements[field].value;
      if (input !== String(metric[field])) values[field] = field === "page" ? Number(input) : input.trim();
    }
  }
  const data = await api("paper-metrics", {
    action, metric_id: metric.id, revision: metric.revision, ...values, reason: metricForm.elements.reason.value,
  });
  if (!metricListingCurrent(listing)) return;
  if (action !== "correct") {
    await reloadPaperMetrics();
    if (selectedPaper()?.id === listing.paperId) {
      metricStatus.textContent = data.removed ? "Metric removed." : "Metric restored.";
    }
    return;
  }
  Object.assign(metric, values, {revision: data.revision});
  const option = Array.from(metricPicker.options).find(option => option.value === String(metric.id));
  option.textContent = metricLabel(metric).slice(0, 180);
  if (metricPicker.value === String(metric.id)) {
    metricStatus.textContent = "Correction saved.";
    await showPaperMetric();
  }
}, metricStatus);
submit(metricEditors, async () => {
  const listing = metricListing;
  const metric = listing.records.get(metricPicker.value);
  await api("metric-editors", {
    metric_id: metric.id, username: metricEditors.elements.username.value,
    action: metricEditors.elements.action.value,
  });
  if (metricListingCurrent(listing) && metricPicker.value === String(metric.id)) {
    metricEditors.elements.username.value = "";
    metricStatus.textContent = "Editor access updated.";
    await loadMetricHistory(listing, metric);
  }
}, metricStatus);
