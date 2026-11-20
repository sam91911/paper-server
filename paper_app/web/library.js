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
  const options = papers.map(item => [item.id, item.title || paperFilename(item)]);
  const current = libraryData.papers.find(item => String(item.id) === selected);
  if (current && !papers.includes(current)) {
    options.unshift([current.id, `${current.title || paperFilename(current)} (selected)`]);
  }
  setOptions(paperPicker, options, papers.length ? "Choose a paper" : "No matching papers");
  if (current) paperPicker.value = selected;
  element("paper-search-status").textContent = invalidYears ? "Enter a valid publication year range."
    : (terms.length || members || publisher || fromYear !== null || throughYear !== null)
      ? `${papers.length} of ${libraryData.papers.length} papers match.` : "";
}

async function loadLibrary(paperId) {
  const previousAccount = libraryData?.account?.id;
  const route = papersPage ? "paper-details" : accountPage ? "account" : documentsPage ? "documents" : "compare";
  libraryData = await api(route);
  if (accountPage) {
    showAccount();
    showKeys();
    return;
  }
  if (documentsPage) {
    showDocuments(libraryData.account?.id !== previousAccount);
    if (previousAccount === undefined) openRequestedDocument();
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
    showPaper();
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
    if (libraryData) updatePaperOptions();
  });
}
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

const documentPicker = element("document-picker");
const documentEditor = element("document-editor");
const documentFile = element("document-file");
const documentStatus = element("document-status");
const documentPreview = element("document-preview");
let editingDocument;
let editingRevision;
let documentParent = null;
const documentCommentForm = element("document-comment-form");

function setDocumentReply(comment) {
  documentParent = comment?.id ?? null;
  const context = element("document-reply-context");
  context.hidden = !comment;
  context.textContent = comment ? `Replying to ${comment.author_name || "an unknown author"}` : "";
  element("cancel-document-reply").hidden = !comment;
  element("post-document-comment").textContent = comment ? "Post reply" : "Add comment";
}

function renderDocumentComments(item) {
  element("document-discussion").hidden = !item;
  if (!item) return;
  const comments = libraryData.comments.filter(comment => comment.document_id === item.id);
  if (!comments.some(comment => comment.id === documentParent && !comment.deleted)) setDocumentReply(null);
  renderComments(element("document-comments"), element("document-comment-summary"), comments,
    { document_id: item.id }, "document", documentStatus, comment => {
      setDocumentReply(comment);
      documentCommentForm.elements.body.focus();
    });
}

element("cancel-document-reply").addEventListener("click", () => setDocumentReply(null));
submit(documentCommentForm, async () => {
  const item = selectedDocument();
  const fields = documentCommentForm.elements;
  const line = fields.line.valueAsNumber;
  await api("comments", {
    document_id: item.id, body: fields.body.value, audience: fields.audience.value,
    doi_refs: doiLines(fields.doi_refs.value),
    recipients: recipientNames(fields.recipients.value), parent_id: documentParent,
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

function openRequestedDocument() {
  const requested = new URLSearchParams(location.search);
  const id = requested.get("document");
  if (id === null) return;
  documentPicker.value = id;
  const item = selectedDocument();
  if (!item) {
    documentPicker.value = "";
    documentStatus.textContent = "This document is unavailable.";
    return;
  }
  openDocument(item);
  const line = Number(requested.get("line"));
  if (Number.isSafeInteger(line) && line > 0) {
    const text = item.markdown.split("\n")[line - 1];
    if (text === undefined) {
      documentStatus.textContent = `Source line ${line} is no longer present.`;
    } else {
      const marker = add(documentPreview, "p", `Source line ${line}`, "document-location");
      add(add(documentPreview, "pre"), "code", text);
      marker.scrollIntoView({ block: "center" });
    }
  }
}

function openDocument(item, { create = false } = {}) {
  editingDocument = item?.id ?? (create ? "new" : undefined);
  editingRevision = item?.revision;
  documentCommentForm.reset();
  setDocumentReply(null);
  element("review-document").hidden = !item;
  renderDocumentComments(item);
  const canEdit = create || (item && item.owner_id === libraryData.account?.id);
  documentEditor.hidden = !canEdit;
  element("document-layout").classList.toggle("is-editing", Boolean(canEdit));
  element("document-preview-panel").hidden = !item && !create;
  closePdf("document");
  element("download-document").hidden = !item;
  element("document-owner").textContent = item
    ? `${item.owner_name}${item.owner_role === "user" ? "" : ` (${roleLabels[item.owner_role]})`} · ${audienceLabels[item.audience]}`
    : "";
  documentStatus.textContent = "";
  documentEditor.reset();
  documentEditor.elements.title.value = item?.title || "";
  documentEditor.elements.markdown.value = item?.markdown || "";
  selectAudience(documentEditor.elements.audience, item?.audience || "owner");
  documentEditor.elements.recipients.value = (item?.recipients || []).join(", ");
  renderMarkdown(item?.markdown || "");
}

function showDocuments(accountChanged) {
  const account = libraryData.account;
  element("documents-workspace").hidden = !account;
  element("documents-sign-in").hidden = Boolean(account);
  setOptions(documentPicker, libraryData.documents.map(item => [item.id, item.title]), "Choose a document");
  setOptions(documentFile, libraryData.papers.filter(paper => paper.has_pdf)
    .map(paper => [paper.id, paper.title || paperFilename(paper)]), "Choose a PDF");
  const current = selectedDocument();
  if (accountChanged || (!current && editingDocument !== "new")) openDocument(current);
  else renderDocumentComments(current);
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

documentPicker.addEventListener("change", () => openDocument(selectedDocument()));
element("new-document").addEventListener("click", () => {
  documentPicker.value = "";
  openDocument(null, { create: true });
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
  try {
    const fields = documentEditor.elements;
    const result = await api("documents", {
      document_id: selectedDocument()?.id, revision: editingRevision, title: fields.title.value,
      audience: fields.audience.value, markdown: fields.markdown.value,
      recipients: recipientNames(fields.recipients.value),
    });
    await loadLibrary();
    documentPicker.value = String(result.document_id);
    openDocument(selectedDocument());
    documentStatus.textContent = "Document saved.";
  } catch (error) {
    documentStatus.textContent = error.message;
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
  element("copy-agent-check").dataset.command = `${python} -m paper_app.local_ai --check`;
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
  agentCommand.value = `${python} -m paper_app.local_ai ${target} --port ${port} ${options}${agentPost.checked ? " --post" : ""}`;
  element("copy-agent-command").disabled = false;
  element("agent-prerequisites").textContent = agentEngine.value === "cloud"
    ? "Run from the project directory with a Cloud AI application key. Set PAPER_AI_CLOUD_URL and PAPER_AI_CLOUD_MODEL. The command asks before sending context to that provider."
    : "Run from the project directory with a Local AI application key. Replace the model path with your GGUF file. Install llama-completion, and use pdftotext for PDFs.";
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

libraryPanel.hidden = !papersPage;
element("account-page").hidden = !accountPage;
element("markdown-documents").hidden = !documentsPage;
const [page, title] = papersPage ? ["papers", "Papers"]
  : documentsPage ? ["documents", "Markdown documents"]
  : accountPage ? ["account", "Account"]
  : ["compare", "Compare metrics"];
element(`${page}-link`).setAttribute("aria-current", "page");
element("page-title").textContent = title;
document.title = title;
element("chart-group-label").hidden = !comparePage;
for (const item of document.querySelectorAll(".compare-only")) item.hidden = !comparePage;
const pageStatus = accountPage ? accountStatus : documentsPage ? documentStatus : papersPage ? libraryStatus : status;
if (accountPage && new URLSearchParams(location.search).get("google") === "failed") {
  accountStatus.textContent = "Google sign-in failed or expired. Try again.";
  history.replaceState(null, "", "/account");
}
loadLibrary().catch(error => { pageStatus.textContent = error.message; });
