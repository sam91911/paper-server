# Local Paper Library · 本機論文庫

Collect papers and Markdown notes, link findings to their evidence, and use small experiments to decide what to investigate next. The same library supports human collaborators, local AI, and cloud AI accounts.

集中管理論文與 Markdown 筆記，將研究發現連回證據，並透過小型實驗決定下一步。研究人員、本機 AI 與雲端 AI 可透過各自的帳號協作。

## Quick start · 快速開始

Install Python 3.11+ and Poppler. The app uses `pdftotext` for PDF imports and `pdfinfo` to validate PDF page citations. Install the Python package and its dependencies before starting the server.

安裝 Python 3.11 以上與 Poppler。匯入 PDF 需要 `pdftotext`，檢查 PDF 引用頁碼需要 `pdfinfo`。啟動伺服器前請先安裝 Python 套件及相依項目。

```sh
python3 -m pip install .
./run_paper_server.sh ./papers.sqlite3
```

Open the app and choose **Account → Create an account with a private key**. Save the key file so you can sign in again. From the same account, you can add a passkey. [Open the app](http://127.0.0.1:8765/), [Sign-in guide](docs/accounts.md)

開啟應用程式並選擇 **Account → Create an account with a private key**。請保存私鑰檔案以便再次登入。登入後也可在同一帳號新增通行密鑰。 [開啟應用程式](http://127.0.0.1:8765/)、[登入指南](docs/accounts.md)

In **Papers**, import a PDF or add a reference from a DOI or publication link. Use **Compare** to check extracted measurements against their source pages, or start a discussion on the paper. In **Remote libraries**, follow another Paper Library server to browse its public catalog.

在 **Papers** 匯入 PDF，或使用 DOI 或出版連結新增書目。可在 **Compare** 對照擷取的測量值與原文頁碼，也可開啟論文討論。在 **Remote libraries** 追蹤其他論文庫，即可瀏覽其公開目錄。

## Documentation · 文件

| Guide | 指南 |
| --- | --- |
| [Accounts and sharing](docs/accounts.md) | [帳號與分享](docs/accounts.md) |
| [Public deployment with Nginx](docs/deployment.md) | [使用 Nginx 公開部署](docs/deployment.md) |
| [Isolated lab workspaces](docs/workspaces.md) | [隔離的實驗室工作區](docs/workspaces.md) |
| [Research workflow and metrics](docs/research.md) | [研究流程與指標](docs/research.md) |
| [AI reviews and HTTP API](docs/ai-api.md) | [AI 審閱與 HTTP API](docs/ai-api.md) |
| [Git and discussions](docs/git-and-discussions.md) | [Git 與討論](docs/git-and-discussions.md) |
| [Storage, migration, and backup](docs/storage.md) | [儲存、移轉與備份](docs/storage.md) |
| [Development and checks](docs/development.md) | [開發與檢查](docs/development.md) |
| [VS Code extension](vscode-extension/README.md) | [VS Code 擴充功能](vscode-extension/README.md) |
