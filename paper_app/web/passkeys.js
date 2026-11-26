"use strict";

function passkeySupported() {
  return window.isSecureContext && typeof PublicKeyCredential !== "undefined" && Boolean(navigator.credentials);
}

function decodePasskeyBytes(value) {
  return Uint8Array.from(atob(value.replaceAll("-", "+").replaceAll("_", "/")), char => char.charCodeAt(0));
}

function encodePasskeyBytes(value) {
  return btoa(Array.from(new Uint8Array(value), byte => String.fromCharCode(byte)).join(""))
    .replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function passkeyOptions(options, register) {
  const parser = register ? PublicKeyCredential.parseCreationOptionsFromJSON : PublicKeyCredential.parseRequestOptionsFromJSON;
  if (parser) return parser.call(PublicKeyCredential, options);
  const result = {...options, challenge: decodePasskeyBytes(options.challenge)};
  if (register) result.user = {...options.user, id: decodePasskeyBytes(options.user.id)};
  const list = register ? "excludeCredentials" : "allowCredentials";
  if (options[list]) result[list] = options[list].map(item => ({...item, id: decodePasskeyBytes(item.id)}));
  return result;
}

function passkeyCredential(credential) {
  if (!credential) throw new Error("The passkey request was canceled.");
  if (credential.toJSON) return credential.toJSON();
  const response = {};
  for (const name of ["clientDataJSON", "attestationObject", "authenticatorData", "signature", "userHandle"]) {
    if (credential.response[name]) response[name] = encodePasskeyBytes(credential.response[name]);
  }
  return {id: credential.id, rawId: encodePasskeyBytes(credential.rawId), type: credential.type, response};
}

function showPasskeys() {
  const account = libraryData.account;
  const supported = passkeySupported();
  element("passkey-login").hidden = Boolean(account) || !supported;
  element("passkey-panel").hidden = !["user", "member"].includes(account?.role);
  element("passkey-register").hidden = !supported;
  const list = element("passkey-list");
  list.replaceChildren();
  const keys = libraryData.passkeys || [];
  if (!keys.length) add(list, "p", "No passkeys added.");
  for (const key of keys) {
    const form = add(list, "form", undefined, "archive-row");
    add(form, "span", key.label);
    add(form, "button", "Remove passkey", "secondary");
    submit(form, async () => {
      await api("passkeys/revoke", {id: key.id});
      await showHumanKeySession("Passkey removed. Sign in again with another credential.");
    }, accountStatus);
  }
}

submit(element("passkey-login"), async () => {
  if (!passkeySupported()) throw new Error("Passkeys require a supported browser and a secure origin.");
  const {ceremony, options} = await api("passkeys/login-options", {});
  const credential = await navigator.credentials.get({publicKey: passkeyOptions(options, false)});
  await api("passkeys/login", {ceremony, credential: passkeyCredential(credential)});
  await showHumanKeySession("Signed in with your passkey.");
}, accountStatus);

const passkeyRegister = element("passkey-register");
submit(passkeyRegister, async () => {
  if (!passkeySupported()) throw new Error("Passkeys require a supported browser and a secure origin.");
  const label = passkeyRegister.elements.label.value;
  const {ceremony, options} = await api("passkeys/register-options", {});
  const credential = await navigator.credentials.create({publicKey: passkeyOptions(options, true)});
  await api("passkeys/register", {ceremony, label, credential: passkeyCredential(credential)});
  await loadLibrary();
  accountStatus.textContent = "Passkey added.";
}, accountStatus);
