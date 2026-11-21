"use strict";

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
