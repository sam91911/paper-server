"use strict";

const picker = document.getElementById("library-origin");
const form = document.getElementById("follow-library");
const status = document.getElementById("public-status");
const papers = document.getElementById("public-papers");
const more = document.getElementById("more-public-papers");
const unfollow = document.getElementById("unfollow-library");
const storageKey = "paper-library-followed-origins";
let origins = [];
let cursor = null;
let request = null;

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

function addLink(parent, label, href) {
  const link = document.createElement("a");
  link.href = href;
  link.textContent = label;
  link.referrerPolicy = "no-referrer";
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
  const heading = document.createElement("h2");
  const source = new URL("/public-library", origin);
  source.searchParams.set("paper", paper.id);
  addLink(heading, paper.title || paper.doi || "Published reference", source);
  item.append(heading);
  if (paper.doi && typeof paper.doi === "string") {
    addLink(item, paper.doi, "https://doi.org/" + paper.doi.split("/").map(encodeURIComponent).join("/"));
  }
  if (typeof paper.source_url === "string" && paper.source_url) {
    try {
      const url = new URL(paper.source_url);
      if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) {
        const link = document.createElement("p");
        addLink(link, "Publication link", url);
        item.append(link);
      }
    } catch { /* Skip invalid links. */ }
  }
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
  const url = new URL("/api/public-papers", origin);
  if (after) url.searchParams.set("after", after);
  if (paperId) url.searchParams.set("paper_id", paperId);
  if (!after) papers.replaceChildren();
  more.hidden = true;
  status.textContent = `Loading from ${origin}…`;
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
    more.hidden = !cursor;
    status.textContent = papers.childElementCount ? `Source: ${origin}` : "No public papers found.";
  } catch {
    if (request === current) status.textContent = `Could not load the public catalog from ${origin}.`;
  } finally {
    clearTimeout(timer);
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
    load();
  } catch (error) {
    status.textContent = error.message;
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
choose(location.origin);
load({paperId: new URLSearchParams(location.search).get("paper")});
