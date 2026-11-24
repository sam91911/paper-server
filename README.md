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

Open the app, choose **Account → Create an account with a private key**, then upload a PDF under **Papers** or create a note under **Documents**. Use **Compare** to filter extracted metrics and check their source pages before drawing conclusions. Press Ctrl+C to stop the server. Add `--port 9000` to the command to use a different port. [Open the app](http://127.0.0.1:8765/)

開啟應用程式，選擇 **Account → Create an account with a private key**，接著在 **Papers** 上傳 PDF，或在 **Documents** 建立筆記。可在 **Compare** 篩選擷取的指標，並在下結論前核對原文頁碼。按 Ctrl+C 停止伺服器。若需更換連接埠，可在指令後加上 `--port 9000`。 [開啟應用程式](http://127.0.0.1:8765/)

## Documentation · 文件

| Guide | 指南 |
| --- | --- |
| [Accounts and sharing](docs/accounts.md) | [帳號與分享](docs/accounts.md) |
| [Public deployment with Nginx](docs/deployment.md) | [使用 Nginx 公開部署](docs/deployment.md) |
| [Research workflow and metrics](docs/research.md) | [研究流程與指標](docs/research.md) |
| [AI reviews and HTTP API](docs/ai-api.md) | [AI 審閱與 HTTP API](docs/ai-api.md) |
| [Storage, migration, and backup](docs/storage.md) | [儲存、移轉與備份](docs/storage.md) |
| [Development and checks](docs/development.md) | [開發與檢查](docs/development.md) |
| [VS Code extension](vscode-extension/README.md) | [VS Code 擴充功能](vscode-extension/README.md) |
