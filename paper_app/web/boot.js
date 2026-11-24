"use strict";

libraryPanel.hidden = !papersPage;
element("account-page").hidden = !accountPage;
element("markdown-documents").hidden = !documentsPage;
const [page, title] = papersPage ? ["papers", "Papers"]
  : newsPage ? ["news", "News"]
  : documentsPage ? ["documents", "Markdown documents"]
  : accountPage ? ["account", "Account"]
  : ["compare", "Compare metrics"];
element(`${page}-link`).setAttribute("aria-current", "page");
element("page-title").textContent = title;
element("page-description").textContent = {
  papers: "Browse your library, read PDFs, and discuss the evidence.",
  news: "Share news sources, discuss what changed, and propose research directions.",
  documents: "Write research notes and connect findings to their sources.",
  account: "Manage sign-in keys, invitations, and connected agents.",
  compare: "Compare measurements across papers, units, and experimental conditions.",
}[page];
document.title = title;
element("chart-group-label").hidden = !comparePage;
for (const item of document.querySelectorAll(".compare-only")) item.hidden = !comparePage;
const pageStatus = accountPage ? accountStatus : documentsPage ? documentStatus : papersPage ? libraryStatus : status;
if (accountPage && new URLSearchParams(location.search).get("google") === "failed") {
  accountStatus.textContent = "Google sign-in failed or expired. Try again.";
  history.replaceState(null, "", "/account");
}
loadLibrary().catch(error => { pageStatus.textContent = error.message; });
