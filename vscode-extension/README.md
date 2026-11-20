# Local Paper Library for VS Code

Edit documents and post private comments using your Paper Library account.

1. Start the Paper Library server.
2. Create an application key on its **Account** page.
3. Run **Paper Library: Configure Server and Key** in the VS Code Command Palette. Enter the server URL and port, then the key.
4. Run **Paper Library: Open Document** or **New Document**. Save with the normal VS Code save command. The library enforces ownership and rejects stale saves.
5. Use **Paper Library: Post Comment** to comment on a paper or document, or reply to a visible comment. You can type the comment or use selected editor text.

VS Code stores the key in Secret Storage for the specific server origin. The extension accepts HTTP loopback URLs and HTTPS origins. The bundled server binds to loopback. For a different machine, use a trusted reverse proxy or forward its loopback port over SSH.
