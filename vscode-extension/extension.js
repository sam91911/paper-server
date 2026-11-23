"use strict";

const { createHash } = require("node:crypto");
const vscode = require("vscode");
const { serverOrigin, request } = require("./client");

const SCHEME = "paper-library";
const secretName = origin => `paper-library.key:${origin}`;
const originTag = origin => createHash("sha256").update(origin).digest("hex").slice(0, 24);

function configuration() {
  return vscode.workspace.getConfiguration("paperLibrary");
}

function configuredOrigin() {
  return serverOrigin(configuration().get("server"));
}

function documentUri(origin, account, item) {
  const title = item.title.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_");
  return vscode.Uri.from({
    scheme: SCHEME, authority: originTag(origin),
    path: `/${item.id}/${title}.md`, query: String(account.id),
  });
}

function locationFor(uri) {
  const id = Number(uri.path.split("/")[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

function fileInfo(item, user) {
  return {
    type: vscode.FileType.File, ctime: 0,
    mtime: Date.parse(item.updated.replace(" ", "T") + "Z") || 0,
    size: Buffer.byteLength(item.markdown, "utf8"),
    permissions: item.owner_id === user.id ? undefined : vscode.FilePermission.Readonly,
  };
}

function activate(context) {
  const cache = new Map();
  const emitter = new vscode.EventEmitter();

  async function connection() {
    const origin = configuredOrigin();
    const key = await context.secrets.get(secretName(origin));
    if (!key) throw new Error("Run Paper Library: Configure Server and Key first.");
    const send = (route, data) => request(origin, key, route, data);
    const { account } = await send("/api/account");
    if (!account) throw new Error("The application key is invalid or revoked.");
    return { origin, account, send };
  }

  function validateUri(uri, session) {
    const id = locationFor(uri);
    if (!id || uri.authority !== originTag(session.origin) || uri.query !== String(session.account.id)) {
      throw vscode.FileSystemError.NoPermissions("This editor belongs to a different server or account.");
    }
    return id;
  }

  async function readRecord(uri) {
    const session = await connection();
    const id = validateUri(uri, session);
    const { document } = await session.send(`/api/document?id=${id}`);
    return { session, document };
  }

  const unavailable = () => vscode.FileSystemError.NoPermissions("Manage these files through Paper Library commands.");
  const provider = {
    onDidChangeFile: emitter.event,
    watch: () => new vscode.Disposable(() => {}),
    readDirectory: () => [],
    createDirectory() { throw unavailable(); },
    delete() { throw unavailable(); },
    rename() { throw unavailable(); },
    async stat(uri) {
      const { session, document } = await readRecord(uri);
      return fileInfo(document, session.account);
    },
    async readFile(uri) {
      const { document } = await readRecord(uri);
      cache.set(uri.toString(), document);
      return Buffer.from(document.markdown, "utf8");
    },
    async writeFile(uri, content) {
      const session = await connection();
      const id = validateUri(uri, session);
      const previous = cache.get(uri.toString());
      if (!previous || previous.owner_id !== session.account.id) throw unavailable();
      const markdown = Buffer.from(content).toString("utf8");
      const result = await session.send("/api/documents", {
        document_id: id, revision: previous.revision, title: previous.title,
        markdown, audience: previous.audience,
      });
      cache.set(uri.toString(), { ...previous, revision: result.revision, markdown });
      emitter.fire([{ type: vscode.FileChangeType.Changed, uri }]);
    },
  };

  function register(name, action) {
    const command = vscode.commands.registerCommand(`paperLibrary.${name}`, async () => {
      try { await action(); }
      catch (error) { vscode.window.showErrorMessage(error.message); }
    });
    context.subscriptions.push(command);
  }

  async function open(session, item) {
    const doc = await vscode.workspace.openTextDocument(documentUri(session.origin, session.account, item));
    await vscode.window.showTextDocument(doc);
  }

  register("connect", async () => {
    const input = await vscode.window.showInputBox({
      title: "Paper Library server", value: configuration().get("server"),
      prompt: "Include the port, for example http://127.0.0.1:8765",
      validateInput(value) {
        try { serverOrigin(value); return undefined; }
        catch (error) { return error.message; }
      },
    });
    if (input === undefined) return;
    const origin = serverOrigin(input);
    const key = await vscode.window.showInputBox({
      title: "Paper Library application key",
      prompt: `Create a key on the Account page at ${origin}`,
      password: true, ignoreFocusOut: true,
      validateInput: value => /^pl_[A-Za-z0-9_-]{43}$/.test(value.trim()) ? undefined : "Enter a Paper Library key.",
    });
    if (key === undefined) return;
    const { account } = await request(origin, key.trim(), "/api/account");
    if (!account) throw new Error("This server did not accept the application key.");
    await context.secrets.store(secretName(origin), key.trim());
    await configuration().update("server", origin, vscode.ConfigurationTarget.Global);
    vscode.window.showInformationMessage(`Connected as ${account.username}.`);
  });

  register("forgetKey", async () => {
    await context.secrets.delete(secretName(configuredOrigin()));
    cache.clear();
    vscode.window.showInformationMessage("Paper Library key removed from VS Code.");
  });

  register("openDocument", async () => {
    const session = await connection();
    const { documents } = await session.send("/api/documents?comments=none&content=summary");
    const choices = documents.map(item => ({
      label: item.title, description: item.owner_id === session.account.id ? "Editable" : "Read only", item,
    }));
    const selected = await vscode.window.showQuickPick(choices, { placeHolder: "Choose a library document" });
    if (selected) await open(session, selected.item);
  });

  register("newDocument", async () => {
    const session = await connection();
    const title = await vscode.window.showInputBox({
      title: "New private paper-library document",
      validateInput: value => value.trim().length > 0 && value.trim().length <= 160
        ? undefined : "Enter a title of up to 160 characters.",
    });
    if (title === undefined) return;
    const result = await session.send("/api/documents", { title, markdown: "", audience: "owner" });
    await open(session, { id: result.document_id, title });
  });

  register("postComment", async () => {
    const editor = vscode.window.activeTextEditor;
    const session = await connection();
    const kind = await vscode.window.showQuickPick(["Paper", "Document"], { placeHolder: "Comment on a paper or document" });
    if (!kind) return;
    const data = await session.send(kind === "Paper" ? "/api/paper-details" : "/api/documents");
    const hostField = kind === "Paper" ? "paper_id" : "document_id";
    const hosts = kind === "Paper" ? data.papers : data.documents;
    const target = await vscode.window.showQuickPick(hosts.map(item => ({
      label: item.title || item.path, description: `#${item.id}`, id: item.id,
    })), { placeHolder: `Choose a ${kind.toLowerCase()}` });
    if (!target) return;
    const comments = data.comments.filter(item => item[hostField] === target.id && !item.deleted);
    const thread = await vscode.window.showQuickPick([
      { label: "New comment", id: null },
      ...comments.map(item => ({ label: `Reply to #${item.id}`, description: item.body.replace(/\s+/g, " ").slice(0, 120), id: item.id })),
    ], { placeHolder: "Start a discussion or reply" });
    if (!thread) return;
    const text = editor && !editor.selection.isEmpty ? editor.document.getText(editor.selection) : "";
    let body;
    if (text) {
      const format = await vscode.window.showQuickPick(["Use editor selection", "Type a comment"], { placeHolder: "Choose comment text" });
      if (!format) return;
      if (format === "Use editor selection") body = text;
    }
    if (body === undefined) {
      body = await vscode.window.showInputBox({
        title: "Post a private comment",
        validateInput: value => value.trim() && value.length <= 20000 ? undefined : "Enter up to 20,000 characters.",
      });
    }
    if (body === undefined) return;
    const confirm = await vscode.window.showInformationMessage(
      "Post this comment with owner-only access?", { modal: true }, "Post",
    );
    if (confirm !== "Post") return;
    await session.send("/api/comments", {
      [hostField]: target.id, parent_id: thread.id, body, audience: "owner",
    });
    vscode.window.showInformationMessage("Private comment posted.");
  });

  context.subscriptions.push(emitter, vscode.workspace.registerFileSystemProvider(SCHEME, provider, { isCaseSensitive: true }));
}

module.exports = { activate };
