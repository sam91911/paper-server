# Local Paper Library for VS Code · VS Code 論文庫擴充功能

Edit library Markdown and post private comments using your Paper Library account. [Set up the library](../README.md)

使用你的論文庫帳號編輯 Markdown 文件與發表私人留言。 [論文庫設定](../README.md)

## Connect · 連線

1. Start the library and create an application key on its **Account** page.

   啟動論文庫，並在 **Account** 頁面建立應用程式金鑰。
2. In VS Code, run **Extensions: Install from VSIX** and select the extension package.

   在 VS Code 執行 **Extensions: Install from VSIX**，選取擴充功能套件。
3. From the Command Palette, run **Paper Library: Configure Server and Key**. Enter `http://127.0.0.1:8765` or your configured address, then paste the key.

   在命令選擇區執行 **Paper Library: Configure Server and Key**。輸入 `http://127.0.0.1:8765` 或自訂位址，接著貼上金鑰。

## Commands · 指令

| Command | What it does | 用途 |
| --- | --- | --- |
| **Open Document** | Open a shared document or edit a document you own. Save with the standard VS Code command. | 開啟已分享的文件，或編輯自己擁有的文件。使用 VS Code 的一般儲存指令。 |
| **New Document** | Create and open a private Markdown document. | 建立並開啟私人 Markdown 文件。 |
| **Post Comment** | Start or reply to a discussion using typed text or your editor selection. New comments are owner-only. | 使用輸入的文字或編輯器選取內容發表或回覆留言。新留言僅擁有者可見。 |
| **Forget Application Key** | Remove this server's key from VS Code. Revoke it on the library's **Account** page if needed. | 從 VS Code 移除此伺服器的金鑰。如需撤銷，請在論文庫的 **Account** 頁面操作。 |

VS Code stores the key separately for each server address in Secret Storage. For a remote server, use SSH port forwarding or an HTTPS reverse proxy. If a save reports a newer revision, copy your edits before reopening the document.

VS Code 依各伺服器位址將金鑰分開存放於 Secret Storage。若伺服器位於其他電腦，請使用 SSH 連接埠轉送或 HTTPS 反向代理。若儲存時顯示文件已有較新版本，請先複製自己的修改，再重新開啟文件。
