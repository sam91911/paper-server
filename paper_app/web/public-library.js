"use strict";

const picker = document.getElementById("library-origin");
const form = document.getElementById("follow-library");
const status = document.getElementById("public-status");
const papers = document.getElementById("public-papers");
const more = document.getElementById("more-public-papers");
const pagination = document.getElementById("remote-pagination");
const unfollow = document.getElementById("unfollow-library");
const retry = document.getElementById("retry-public-papers");
const catalogTitle = document.getElementById("remote-catalog-title");
const catalogOrigin = document.getElementById("remote-catalog-origin");
const catalogLink = document.getElementById("remote-catalog-link");
const fullCatalog = document.getElementById("show-full-catalog");
const followStatus = document.getElementById("follow-status");
const followPanel = document.getElementById("follow-library-panel");
const wideLayout = matchMedia("(min-width: 46rem)");
followPanel.open = wideLayout.matches;
const storageKey = "paper-library-followed-origins";
let origins = [];
let cursor = null;
let request = null;
let failedPage;

function originOf(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("Enter the library’s HTTPS origin.");
  }
  return url.origin;
}

try {
  origins = JSON.parse(localStorage.getItem(storageKey) || "[]").map(originOf);
} catch {
  origins = [];
}

function saveOrigins() {
  localStorage.setItem(storageKey, JSON.stringify(origins));
}

function choose(origin) {
  picker.replaceChildren(new Option("This library", location.origin));
  for (const host of origins) picker.add(new Option(host, host));
  picker.value = origin;
  unfollow.hidden = origin === location.origin;
}

function addLink(parent, label, href, className) {
  const link = document.createElement("a");
  link.href = href;
  link.textContent = label;
  link.referrerPolicy = "no-referrer";
  if (className) link.className = className;
  parent.append(link);
}

async function readCatalog(response) {
  if (!response.ok) throw new Error(`Catalog returned HTTP ${response.status}.`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let bytes = 0;
  let body = "";
  for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
    bytes += chunk.value.byteLength;
    if (bytes > 4_000_000) {
      await reader.cancel();
      throw new Error("Catalog response is too large.");
    }
    body += decoder.decode(chunk.value, {stream: true});
  }
  return JSON.parse(body + decoder.decode());
}

function showPaper(origin, paper) {
  if (!Number.isSafeInteger(paper.id) || paper.id < 1) return;
  const item = document.createElement("li");
  const heading = document.createElement("h3");
  const source = new URL("/public-library", origin);
  source.searchParams.set("paper", paper.id);
  const doi = typeof paper.doi === "string" ? paper.doi : "";
  const title = typeof paper.title === "string" && paper.title.trim();
  addLink(heading, title || doi || "Published reference", source);
  item.append(heading);
  const links = document.createElement("div");
  links.className = "remote-paper-links";
  if (doi) addLink(links, doi, "https://doi.org/" + doi.split("/").map(encodeURIComponent).join("/"), "remote-doi");
  if (typeof paper.source_url === "string" && paper.source_url) {
    try {
      const url = new URL(paper.source_url);
      if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) {
        addLink(links, "Publication link", url);
      }
    } catch { /* Skip invalid links. */ }
  }
  if (links.childElementCount) item.append(links);
  if (typeof paper.summary === "string" && paper.summary) {
    const summary = document.createElement("p");
    summary.textContent = paper.summary;
    item.append(summary);
  }
  papers.append(item);
}

async function load({after = null, paperId = null} = {}) {
  request?.abort();
  const current = new AbortController();
  request = current;
  const origin = picker.value;
  const local = origin === location.origin;
  catalogTitle.textContent = local ? "This library" : new URL(origin).host;
  catalogOrigin.textContent = origin;
  catalogLink.href = new URL("/public-library", origin);
  catalogLink.referrerPolicy = "no-referrer";
  catalogLink.hidden = local;
  fullCatalog.hidden = !paperId;
  const url = new URL("/api/public-papers", origin);
  if (after) url.searchParams.set("after", after);
  if (paperId) url.searchParams.set("paper_id", paperId);
  if (!after) papers.replaceChildren();
  pagination.hidden = true;
  retry.hidden = true;
  failedPage = undefined;
  status.textContent = after ? "Loading more papers…" : "Loading public catalog…";
  papers.setAttribute("aria-busy", "true");
  const timer = setTimeout(() => current.abort(), 15000);
  try {
    const response = await fetch(url, {
      credentials: "omit", redirect: "error", referrerPolicy: "no-referrer", signal: current.signal,
    });
    const data = await readCatalog(response);
    if (request !== current) return;
    if (!Array.isArray(data.papers) || data.papers.length > 50) throw new Error("Invalid public catalog.");
    for (const paper of data.papers) if (paper && typeof paper === "object") showPaper(origin, paper);
    cursor = Number.isSafeInteger(data.next_after) && data.next_after > (after || 0) ? data.next_after : null;
    pagination.hidden = !cursor;
    const count = papers.childElementCount;
    status.textContent = count ? `${count} ${count === 1 ? "paper" : "papers"}${cursor ? " loaded" : ""}`
      : paperId ? "This published reference is unavailable."
      : local ? "No papers have been published from this workspace yet." : "This library has no public papers.";
  } catch {
    if (request === current) {
      status.textContent = after ? "Could not load more papers." : "Could not load this library’s public catalog.";
      failedPage = {after, paperId};
      retry.hidden = false;
    }
  } finally {
    clearTimeout(timer);
    if (request === current) papers.setAttribute("aria-busy", "false");
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  try {
    const origin = originOf(form.elements.origin.value.trim());
    if (origin !== location.origin && !origins.includes(origin)) {
      if (origins.length >= 50) throw new Error("Unfollow a library before adding another.");
      origins.push(origin);
      saveOrigins();
    }
    choose(origin);
    form.reset();
    followStatus.textContent = "";
    if (!wideLayout.matches) {
      followPanel.open = false;
      picker.focus();
    }
    load();
  } catch (error) {
    followStatus.textContent = error.message;
  }
});
picker.addEventListener("change", () => {
  unfollow.hidden = picker.value === location.origin;
  load();
});
unfollow.addEventListener("click", () => {
  origins = origins.filter(origin => origin !== picker.value);
  saveOrigins();
  choose(location.origin);
  load();
});
more.addEventListener("click", () => load({after: cursor}));
retry.addEventListener("click", () => load(failedPage));
fullCatalog.addEventListener("click", () => {
  history.replaceState(null, "", "/public-library");
  load();
});
choose(location.origin);
load({paperId: new URLSearchParams(location.search).get("paper")});
