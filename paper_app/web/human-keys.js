"use strict";

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
      download.download = `paper-library-${owner}.json`;
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
    const profile = action === "register" ? Object.fromEntries(new FormData(form)) : {};
    const proof = await signHumanChallenge(action, owner, key);
    await api(`human-key/${action}`, {...profile, ...proof, public_key: publicKey});
    resetKey();
    form.reset();
    await showHumanKeySession(action === "register" ? "Account created." : "Private-key sign-in added.");
  }, accountStatus);
}

if (accountPage) {
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
