"use strict";

function fillHumanInvitation() {
  const invitation = new URLSearchParams(location.hash.slice(1)).get("invite");
  if (invitation === null) return;
  history.replaceState(null, "", location.pathname + location.search);
  if (!/^[A-Za-z0-9_-]{43}$/.test(invitation)) {
    accountStatus.textContent = "This invitation link is invalid.";
    return;
  }
  element("human-key-register").elements.invite.value = invitation;
  element("signup").elements.invite.value = invitation;
  element("human-key-signup-panel").open = true;
  accountStatus.textContent = "Sign out if needed, then sign up with the email address that received this invitation.";
}

function humanKeyCrypto() {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Private-key sign-in requires HTTPS or a loopback address.");
  }
  return crypto.subtle;
}

async function signHumanChallenge(action, username, privateKey) {
  const {challenge, message} = await api("human-key/challenge", {action, username});
  if (!message.startsWith(`paper-library:human:${action}:${location.origin}:`) || !message.endsWith(`:${challenge}`)) {
    throw new Error("The library returned an invalid sign-in challenge.");
  }
  const signed = await humanKeyCrypto().sign("Ed25519", privateKey, new TextEncoder().encode(message));
  const signature = btoa(String.fromCharCode(...new Uint8Array(signed)))
    .replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
  return {challenge, signature};
}

async function showHumanKeySession(message) {
  notifySessionChange();
  await loadLibrary();
  accountStatus.textContent = message;
}

function showHumanKeys() {
  const list = element("human-key-list");
  const keys = libraryData.sign_in_keys || [];
  list.replaceChildren();
  if (!keys.length) add(list, "p", "No private sign-in keys.");
  const protectLast = libraryData.account?.key_only && keys.length === 1;
  if (protectLast) add(list, "p", "Add a backup key before revoking your last sign-in key.");
  for (const key of keys) {
    const form = add(list, "form", undefined, "archive-row");
    add(form, "span", key.label);
    add(form, "button", "Revoke key", "secondary").disabled = Boolean(protectLast);
    submit(form, async () => {
      await api("human-key/revoke", {key_id: key.key_id});
      await showHumanKeySession("Key revoked. Sign in again with another key or sign-in method.");
    }, accountStatus);
  }
}

function setupHumanKeyEnrollment(action) {
  const form = element(`human-key-${action}`);
  const generate = form.querySelector("[data-generate-key]");
  const download = form.querySelector("[data-download-key]");
  const save = form.querySelector("[data-save-key]");
  const username = () => action === "register" ? form.elements.username.value.trim() : libraryData?.account?.username;
  let pending;

  function resetKey() {
    if (pending) URL.revokeObjectURL(download.href);
    pending = undefined;
    download.removeAttribute("href");
    download.hidden = true;
    save.disabled = true;
  }

  generate.addEventListener("click", async () => {
    if (!form.reportValidity()) return;
    resetKey();
    generate.disabled = true;
    try {
      const owner = username();
      const subtle = humanKeyCrypto();
      const key = await subtle.generateKey("Ed25519", true, ["sign", "verify"]);
      const privateJwk = await subtle.exportKey("jwk", key.privateKey);
      if (owner !== username()) return;
      const contents = JSON.stringify({origin: location.origin, username: owner, key: privateJwk});
      download.href = URL.createObjectURL(new Blob([contents], {type: "application/json"}));
      download.download = `paper-library-${owner}-${privateJwk.x.slice(0, 8)}.json`;
      pending = {username: owner, key: key.privateKey, publicKey: privateJwk.x};
      download.hidden = false;
      accountStatus.textContent = "Download your private key and keep it somewhere safe. You’ll need it to sign in.";
    } catch (error) {
      accountStatus.textContent = error.name === "NotSupportedError"
        ? "Use a browser that supports Ed25519 private keys." : error.message;
    } finally {
      generate.disabled = false;
    }
  });
  download.addEventListener("click", () => { save.disabled = false; });

  submit(form, async () => {
    if (!pending || save.disabled || pending.username !== username()) {
      resetKey();
      throw new Error("Generate and download a key for this username first.");
    }
    const {key, publicKey, username: owner} = pending;
    const profile = Object.fromEntries(new FormData(form));
    const proof = await signHumanChallenge(action, owner, key);
    await api(`human-key/${action}`, {...profile, ...proof, public_key: publicKey});
    resetKey();
    form.reset();
    if (action === "register") element("signup").elements.invite.value = "";
    await showHumanKeySession(action === "register" ? "Account created." : "Private-key sign-in added.");
  }, accountStatus);
}

if (accountPage) {
  fillHumanInvitation();
  window.addEventListener("hashchange", fillHumanInvitation);
  const inviteForm = element("create-human-invitation");
  const inviteResult = element("human-invitation-result");
  const inviteUrl = element("human-invitation-url");
  const invitePanel = element("human-invitation-panel");
  const pendingList = element("pending-human-invitations");
  let invitationRequest = 0;

  function clearInviteLink() {
    inviteUrl.value = "";
    inviteResult.hidden = true;
    delete inviteResult.dataset.inviteId;
  }

  async function loadPendingInvitations() {
    const accountId = libraryData.account?.id;
    const request = ++invitationRequest;
    const {invitations} = await api("human-invitations");
    if (request !== invitationRequest || libraryData.account?.id !== accountId || libraryData.account?.role !== "user") return;
    pendingList.replaceChildren();
    if (!invitations.length) add(pendingList, "p", "No pending invitations.");
    for (const invitation of invitations) {
      const form = add(pendingList, "form", undefined, "archive-row");
      const expires = new Date(invitation.expires * 1000).toLocaleString();
      add(form, "span", `${invitation.email} · ${roleLabels[invitation.role]} · Expires ${expires}`);
      add(form, "button", "Revoke invitation", "secondary");
      submit(form, async () => {
        await api("human-invitations", {action: "revoke", invite_id: invitation.invite_id});
        if (libraryData.account?.id !== accountId) return;
        if (inviteResult.dataset.inviteId === invitation.invite_id) clearInviteLink();
        accountStatus.textContent = "Invitation revoked.";
        await loadPendingInvitations();
      }, accountStatus);
    }
  }

  submit(inviteForm, async () => {
    const accountId = libraryData.account?.id;
    clearInviteLink();
    const {invitation_url, invite_id, role} = await api("human-invitations", {
      email: inviteForm.elements.email.value, role: inviteForm.elements.role.value,
    });
    if (libraryData.account?.id !== accountId || libraryData.account?.role !== "user") return;
    inviteUrl.value = invitation_url;
    element("human-invitation-access").textContent = `Access level: ${roleLabels[role]}`;
    inviteResult.dataset.inviteId = invite_id;
    inviteResult.hidden = false;
    accountStatus.textContent = "";
    await loadPendingInvitations();
  }, accountStatus);
  const refreshInvitations = () => loadPendingInvitations().catch(error => { accountStatus.textContent = error.message; });
  invitePanel.addEventListener("toggle", () => {
    if (invitePanel.open && libraryData?.account?.role === "user") refreshInvitations();
  });
  element("refresh-human-invitations").addEventListener("click", refreshInvitations);
  element("copy-human-invitation").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(inviteUrl.value);
      accountStatus.textContent = "Invitation link copied.";
    } catch {
      inviteUrl.select();
      accountStatus.textContent = "Copy the selected invitation link.";
    }
  });

  const login = element("human-key-login");
  submit(login, async () => {
    const file = login.elements.key_file.files[0];
    if (!file || file.size > 8192) throw new Error("Choose a Paper Library private key file.");
    let identity;
    try {
      identity = JSON.parse(await file.text());
    } catch {
      throw new Error("Choose a Paper Library private key file.");
    }
    if (identity?.origin !== location.origin || typeof identity.username !== "string") {
      throw new Error("Choose a private key file for this library URL.");
    }
    const key = await humanKeyCrypto().importKey("jwk", identity.key, "Ed25519", false, ["sign"]);
    await api("human-key/login", await signHumanChallenge("login", identity.username, key));
    login.reset();
    await showHumanKeySession("Signed in with private key.");
  }, accountStatus);
  setupHumanKeyEnrollment("register");
  setupHumanKeyEnrollment("attach");
}
