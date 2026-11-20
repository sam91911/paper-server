"use strict";

function serverOrigin(input) {
  let url;
  try {
    url = new URL(input.trim());
  } catch {
    throw new Error("Enter the server address and port as a URL.");
  }
  const local = ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash
      || !(url.protocol === "https:" || (url.protocol === "http:" && local))) {
    throw new Error("Use an HTTPS server origin or an HTTP loopback address, with no path.");
  }
  return url.origin;
}

async function request(origin, key, route, data) {
  let response;
  try {
    response = await fetch(new URL(route, origin), {
      method: data === undefined ? "GET" : "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: data === undefined ? undefined : JSON.stringify(data),
      redirect: "error",
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error(`Could not connect to ${origin}.`);
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`The server returned an unexpected response (HTTP ${response.status}).`);
  }
  if (!response.ok) throw new Error(result.error || `Request failed (HTTP ${response.status}).`);
  return result;
}

module.exports = { serverOrigin, request };
