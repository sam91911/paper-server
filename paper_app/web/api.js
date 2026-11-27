"use strict";

async function api(route, data) {
  const options = data === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
  const response = await fetch(`/api/${route}`, options);
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || "Request failed.");
    error.status = response.status;
    throw error;
  }
  return result;
}

async function copyCloneCommand(kind, id, status, branch = "") {
  const url = `${location.origin}/git/${kind}/${id}.git`;
  const git = kind === "projects" ? "git" : "git --config-env=http.extraHeader=PAPER_GIT_AUTH";
  const command = `${git} clone${branch ? ` --branch ${branch}` : ""} "${url}"`;
  try {
    await navigator.clipboard.writeText(command);
    status.textContent = kind === "projects"
      ? "Clone command copied. Enter your username and Git token when prompted."
      : "Clone command copied. Set PAPER_GIT_AUTH to an Authorization header for your Git token or application key.";
  } catch {
    status.textContent = command;
  }
}
