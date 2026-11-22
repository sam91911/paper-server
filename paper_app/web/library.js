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
let paperPage = 0;
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
  accountForm.hidden = Boolean(account);
  element("sign-out").hidden = !account;
  element("change-password").hidden = !account || Boolean(account.google_only);
  element("signup-panel").hidden = Boolean(account);
  element("google-option").hidden = Boolean(account) || !libraryData.google_available;
  const username = element("account-username");
  username.hidden = !account;
  username.textContent = account ? `Username: ${account.username}` : "";
  element("key-panel").hidden = !account;
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
  lookupSequence++;
  const selected = selectedPaper();
  const viewer = element("paper-pdf-viewer");
  const selectedId = selected ? String(selected.id) : "";
  if (viewer.dataset.paper !== selectedId) closePdf("paper");
  viewer.dataset.paper = selectedId;
  paperPicker.title = selected ? selected.title || selected.path : "";
  element("paper-detail").hidden = !selected;
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
  const locations = [
    ...libraryData.papers.filter(paper => paper.has_pdf)
      .map(paper => [`pdf:${paper.id}`, `PDF · ${paper.title || paperFilename(paper)}`]),
    ...libraryData.document_targets.map(doc => [`document:${doc.id}`, `Document · ${doc.title}`]),
  ];
  setOptions(commentForm.elements.target, locations, "No location");
  commentForm.elements.target.value = draft?.target || "";
  if (commentForm.elements.target.selectedIndex < 0) commentForm.elements.target.value = "";
  commentForm.elements.position.value = draft?.position || "";
  showPositionField();
  showReplyTarget(draft?.parentId);
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

  renderPaperComments(selected);
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

function showArchive() {
  const archive = element("archived-papers");
  const papers = libraryData.archived_papers;
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
  if (paperPicker.value) url.searchParams.set("paper", paperPicker.value);
  else url.searchParams.delete("paper");
  if (new URLSearchParams(location.search).get("paper") !== paperPicker.value) url.searchParams.delete("page");
  history.replaceState(null, "", url);
}

function paperFilename(item) {
  return item.path.split(/[\\/]/).pop();
}

function updatePaperOptions(selected = paperPicker.value) {
  const terms = paperSearch.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const members = groupMembers(paperGroupFilter.value);
  const publisher = paperPublisherFilter.value;
  const fromYear = paperYearFrom.value ? paperYearFrom.valueAsNumber : null;
  const throughYear = paperYearTo.value ? paperYearTo.valueAsNumber : null;
  const invalidYears = !paperYearFrom.validity.valid || !paperYearTo.validity.valid
    || (fromYear !== null && throughYear !== null && fromYear > throughYear);
  const papers = libraryData.papers.filter(item => {
    if (invalidYears || (members && !members.has(item.id))) return false;
    if (publisher && item.publisher !== publisher) return false;
    const year = Number(item.year);
    if ((fromYear !== null && (!year || year < fromYear))
        || (throughYear !== null && (!year || year > throughYear))) return false;
    const text = [item.title, item.authors, item.doi, item.venue, paperFilename(item)]
      .filter(Boolean).join(" ").toLowerCase();
    return terms.every(term => text.includes(term));
  });
  const pages = Math.max(1, Math.ceil(papers.length / paperPageSize));
  paperPage = Math.max(0, Math.min(paperPage, pages - 1));
  const displayed = papers.slice(paperPage * paperPageSize, (paperPage + 1) * paperPageSize);
  const options = displayed.map(item => [item.id, item.title || paperFilename(item)]);
  const current = libraryData.papers.find(item => String(item.id) === selected);
  if (current && !displayed.includes(current)) {
    options.unshift([current.id, `${current.title || paperFilename(current)} (selected)`]);
  }
  element("paper-page-status").textContent = `Page ${paperPage + 1} of ${pages}`;
  element("paper-page-previous").disabled = paperPage === 0;
  element("paper-page-next").disabled = paperPage + 1 >= pages;
  setOptions(paperPicker, options, papers.length ? "Choose a paper" : "No matching papers");
  if (current) paperPicker.value = selected;
  element("paper-search-status").textContent = invalidYears ? "Enter a valid publication year range."
    : (terms.length || members || publisher || fromYear !== null || throughYear !== null)
      ? `${papers.length} of ${libraryData.papers.length} papers match.` : "";
}

async function loadLibrary(paperId) {
  const previousAccount = libraryData?.account?.id;
  const route = papersPage ? "paper-details?comments=none" : accountPage ? "account" : documentsPage ? "documents?comments=none&content=summary" : "compare";
  libraryData = await api(route);
  if (accountPage) {
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
  if (papersPage) {
    if (libraryData.account?.id !== previousAccount) commentDrafts.clear();
    showAccount();
    const publishers = [...new Set(libraryData.papers.map(paper => paper.publisher).filter(Boolean))].sort();
    setOptions(paperPublisherFilter, publishers.map(name => [name, name]), "All publishers");
    setOptions(paperGroupFilter, libraryData.groups.map(item => [item.id, item.name]), "All groups");
    const params = new URLSearchParams(location.search);
    const requested = params.get("paper");
    updatePaperOptions(paperId === undefined ? paperPicker.value || requested : String(paperId));
    rememberPaperSelection();
    await loadPaperComments();
    const requestedPage = Number(params.get("page"));
    const selected = selectedPaper();
    if (requested === String(selected?.id) && selected?.has_pdf && Number.isSafeInteger(requestedPage)
        && requestedPage > 0 && element("paper-pdf-viewer").hidden) {
      viewPdf("paper", `${paperPDFURL(selected.id)}#page=${requestedPage}`, selected.title || paperFilename(selected));
    }
    showArchive();
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
  element("paper-detail").hidden = true;
  data.comments = [];
  nextCommentBefore = null;
  element("older-comments").hidden = true;
  if (selected) {
    const result = await api(`paper-comments?paper_id=${selected.id}`);
    if (sequence !== commentLoadSequence || data !== libraryData || selectedPaper()?.id !== selected.id) return;
    data.comments = result.comments;
    nextCommentBefore = result.next_before;
    element("older-comments").hidden = !nextCommentBefore;
  }
  if (sequence === commentLoadSequence && data === libraryData) showPaper();
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
    libraryStatus.textContent = error.message;
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

for (const field of [paperSearch, paperPublisherFilter, paperYearFrom, paperYearTo]) {
  field.addEventListener("input", () => {
    paperPage = 0;
    if (libraryData) updatePaperOptions();
  });
}
paperGroupFilter.addEventListener("change", () => { paperPage = 0; updatePaperOptions(); });
element("paper-page-previous").addEventListener("click", () => { paperPage--; updatePaperOptions(); });
element("paper-page-next").addEventListener("click", () => { paperPage++; updatePaperOptions(); });
paperPicker.addEventListener("change", () => {
  libraryStatus.textContent = "";
  updatePaperOptions();
  rememberPaperSelection();
  loadPaperComments().catch(error => { libraryStatus.textContent = error.message; });
});
groupPicker.addEventListener("change", filterGroups);
metadataForm.addEventListener("input", () => {
  metadataSource = "Manual";
  element("metadata-source").textContent = "Source: Manual";
});

async function importPaper(file, audience, recipients) {
  const response = await fetch("/api/papers", {
    method: "POST",
    headers: {
      "Content-Type": "application/pdf",
      "X-Paper-Filename": encodeURIComponent(file.name),
      "X-Paper-Audience": audience,
      "X-Paper-Recipients": encodeURIComponent(JSON.stringify(recipients)),
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
        const imported = await importPaper(file, audience, recipients);
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
  const target = commentForm.elements.target.value;
  element("comment-position-label").hidden = !target;
  commentForm.elements.position.required = Boolean(target);
  element("comment-position-text").textContent = target.startsWith("pdf:") ? "PDF page" : "Document line";
}

function rememberCommentDraft(parentId) {
  const id = selectedPaper().id;
  commentDrafts.set(id, {
    body: newComment.value, kind: commentForm.elements.kind.value,
    doiRefs: commentForm.elements.doi_refs.value, audience: commentForm.elements.audience.value, parentId,
    target: commentForm.elements.target.value, position: commentForm.elements.position.value,
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
  const paper = selectedPaper();
  await updateLibrary("archive-paper", { paper_id: paper.id, archived: true }, "Paper archived.");
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
const agentEngine = element("agent-engine");
const agentPlatform = element("agent-platform");
const agentPosition = element("agent-position");
const agentPost = element("agent-post");
const agentCommand = element("agent-command");
let agentTarget;

function refreshAgentCommand() {
  const windows = agentPlatform.value === "windows";
  const python = windows ? "py -3" : "python3";
  element("copy-agent-check").dataset.command = `${python} -m paper_client --check`;
  const port = Number(location.port) || 8765;
  let target = agentTarget.kind === "paper" ? String(agentTarget.id) : `--${agentTarget.kind} ${agentTarget.id}`;
  if (agentTarget.kind !== "thread" && agentPosition.value && !agentPosition.validity.valid) {
    agentCommand.value = "";
    element("copy-agent-command").disabled = true;
    return;
  }
  if (agentTarget.kind === "paper") target += ` --page ${agentPosition.valueAsNumber || 1}`;
  if (agentTarget.kind === "document" && agentPosition.value) target += ` --line ${agentPosition.valueAsNumber}`;
  const localModel = windows ? '"C:\\models\\model.gguf"' : '"/path/to/model.gguf"';
  const options = agentEngine.value === "cloud" ? "--cloud" : `--model ${localModel}`;
  agentCommand.value = `${python} -m paper_client ${target} --port ${port} ${options}${agentPost.checked ? " --post" : ""}`;
  element("copy-agent-command").disabled = false;
  element("agent-prerequisites").textContent = agentEngine.value === "cloud"
    ? "Run on the computer with the paper client and a Cloud AI application key. Set PAPER_AI_CLOUD_URL and PAPER_AI_CLOUD_MODEL. The command asks before sending context to that provider."
    : "Run on the computer with the paper client and a Local AI application key. Replace the model path with your GGUF file. Install llama-completion, and use pdftotext for PDFs.";
}

async function openAgent(kind, id, label, position = "") {
  if (!libraryData.account) {
    libraryStatus.textContent = "Sign in to prepare an AI review.";
    return;
  }
  agentTarget = { kind, id };
  element("agent-target").textContent = label;
  element("agent-position-field").hidden = kind === "thread";
  element("agent-position-label").textContent = kind === "document" ? "Source line (optional)" : "PDF page";
  agentPosition.value = position || (kind === "paper" ? "1" : "");
  agentPost.checked = false;
  const platform = String(navigator.userAgentData?.platform || navigator.platform).toLowerCase();
  agentPlatform.value = platform.includes("win") ? "windows" : platform.includes("mac") ? "macos" : "linux";
  element("copy-agent-status").textContent = "";
  element("agent-tools").textContent = "Checking installed tools on the library server…";
  refreshAgentCommand();
  agentDialog.showModal();
  try {
    const tools = await api("agent-options");
    const serverOs = tools.server_os === "Darwin" ? "macOS" : tools.server_os;
    element("agent-tools").textContent = `Server host (${serverOs}): llama-completion ${tools.llama ? "available" : "missing"}, pdftotext ${tools.pdf_text ? "available" : "missing"}. A browser cannot inspect installed tools on a different computer.`;
  } catch (error) {
    element("agent-tools").textContent = error.message;
  }
}

for (const field of [agentEngine, agentPlatform, agentPosition, agentPost]) {
  field.addEventListener("input", refreshAgentCommand);
}
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
element("copy-agent-command").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(agentCommand.value);
    element("copy-agent-status").textContent = "Command copied.";
  } catch {
    agentCommand.select();
    element("copy-agent-status").textContent = "Command selected. Copy it with your keyboard.";
  }
});

element("copy-agent-check").addEventListener("click", async event => {
  const command = event.currentTarget.dataset.command;
  try {
    await navigator.clipboard.writeText(command);
    element("copy-agent-status").textContent = "Tool check command copied.";
  } catch {
    element("copy-agent-status").textContent = command;
  }
});
