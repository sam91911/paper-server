# Clients and API · 用戶端與 API

[Project home · 專案首頁](../README.md)

Share a paper, document, or comment thread with the AI account. Choose **Review with AI**, select an eligible AI account, and select **Request review**. The dialog shows the result once the AI responds. The optional comment is visible only to the assigned AI account.

先將論文、文件或留言討論串分享給 AI 帳號。在 **Review with AI** 選取有存取權限的 AI 帳號，再選擇 **Request review**。AI 回覆後，結果會顯示在對話框中。若選擇一併發表留言，該留言僅指派的 AI 帳號可見。

If only one account can access the selected source, the dialog selects it automatically. For a thread, the account needs access to the selected comment, its parents, and any linked sources. The review stays queued until that account’s worker picks it up.

若只有一個 AI 帳號可讀取所選來源，系統會自動選取該帳號。審閱討論串時，帳號需要讀取所選留言、上層留言及引用來源的權限。請求會排隊等待該帳號的用戶端接收。

Install the workstation client with `python3 -m pip install ./paper_client` or run it from the repository. Start one worker per AI account using its application key. The worker uses the library API port and handles later requests automatically. For a remote library, forward its port to loopback and pass the forwarded port with `--port`.

使用 `python3 -m pip install ./paper_client` 安裝工作站用戶端，也可直接從儲存庫執行。以各 AI 帳號的應用程式金鑰各啟動一個背景用戶端。用戶端透過論文庫的 API 連接埠接收後續請求。若論文庫位於遠端，請將連接埠轉送到本機回送介面，再使用 `--port` 指定轉送後的連接埠。

| Mode | Setup | 設定方式 |
| --- | --- | --- |
| Local AI · 本機 AI | Install `llama-completion` and use a GGUF model. PDF review needs `pdftotext` on the workstation. | 安裝 `llama-completion` 並使用 GGUF 模型。審閱 PDF 時，工作站須備有 `pdftotext`。 |
| Cloud AI · 雲端 AI | Set `PAPER_AI_CLOUD_URL` to your provider's HTTPS Chat Completions endpoint and `PAPER_AI_CLOUD_MODEL` to its model ID. The worker asks for confirmation before sending each review. | 將 `PAPER_AI_CLOUD_URL` 設為供應商的 HTTPS Chat Completions 端點，並將 `PAPER_AI_CLOUD_MODEL` 設為模型 ID。用戶端在每次送出審閱資料前都會要求確認。 |

```sh
python3 -m paper_client --watch --port 8765 --model /path/to/model.gguf
# Cloud worker / 雲端用戶端
python3 -m paper_client --watch --port 8765 --cloud
```

An AI client can also follow **Skills → Default API skill** to read and complete assignments directly over HTTP. The skill is built in and available through `GET /api/skills/default`. For additional review guidance, add `--skill ID` to the workstation command.

AI 用戶端也可依 **Skills → Default API skill** 的指引，直接以 HTTP 取得並完成指派。此內建技能可透過 `GET /api/skills/default` 讀取。若要為工作站加入其他審閱指引，可在啟動指令加上 `--skill ID`。

Local and cloud accounts use the same HTTP endpoints with their own application keys. The OpenAPI contract describes request fields and responses. The VS Code extension can edit documents and post comments. [OpenAPI JSON](http://127.0.0.1:8765/api/openapi.json) · [VS Code setup](../vscode-extension/README.md)

本機與雲端 AI 帳號使用同一組 HTTP 端點，並各自使用應用程式金鑰。OpenAPI 規格列出請求欄位與回應格式。VS Code 擴充功能可編輯文件與發表留言。 [OpenAPI JSON](http://127.0.0.1:8765/api/openapi.json) · [VS Code 設定](../vscode-extension/README.md)

```sh
curl -fsS -H "Authorization: Bearer $PAPER_APP_KEY" \
  'http://127.0.0.1:8765/api/paper-catalog?q=benchmark'
```
