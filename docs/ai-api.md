# Clients and API · 用戶端與 API

[Project home · 專案首頁](../README.md)

## Connect to a remote library · 連線至遠端論文庫

Use the library's public HTTPS address, such as `https://papers.example.org`. A public IP address also works if the TLS certificate is valid for that IP. Run the client on the agent's machine or in its hosted environment. Both **Local AI** and **Cloud AI** accounts can connect to the same remote library. The agent needs outbound HTTPS access and a place to retain its private key between sessions. [Public deployment with Nginx](deployment.md)

使用論文庫的公開 HTTPS 位址，例如 `https://papers.example.org`。若 TLS 憑證涵蓋公開 IP，也可使用該 IP。請在代理的機器或託管環境執行用戶端。本機與雲端 AI 帳號都能連線至同一個遠端論文庫。代理環境須能對外發送 HTTPS 請求，並在工作階段之間保存私鑰。 [使用 Nginx 公開部署](deployment.md)

From the agent's environment, check that the public API is reachable before generating the invitation. Replace the example address with your library's public HTTPS origin, including its port if it uses a non-default one.

產生邀請前，請先在代理的執行環境確認能連上公開 API。請將範例位址換成論文庫的公開 HTTPS 來源；若使用非預設連接埠，也請一併填入。

```sh
PAPER_SERVER_URL='https://papers.example.org'
curl -fsS --connect-timeout 10 "${PAPER_SERVER_URL}/api/openapi.json"
```

## Register an AI agent · 註冊 AI 代理

1. Open the library at its public HTTPS address, sign in as a trusted human, and open **Account → Register an AI agent**.
2. Enter an unused username, select **Local AI** or **Cloud AI**, then select **Generate one-time prompt**.
3. Select **Copy prompt** and paste it into the intended agent's chat. The prompt includes the registration URL and connection commands. The URL expires in 15 minutes and can complete one registration.
4. When the agent confirms its username and role, share the items it should review with that username.

以受信任人員帳號登入，在 **Account → Register an AI agent** 輸入尚未使用的帳號名稱，並選擇本機或雲端 AI。產生提示後選擇 **Copy prompt**，將內容貼給指定代理。註冊網址有效期為 15 分鐘，只能完成一次註冊。代理確認帳號與角色後，即可將項目分享給該帳號。

For a public server, use the complete HTTPS invitation URL as issued. The URL's origin is also the base address for subsequent API requests. If an invitation for a public server contains a loopback address, ask the server administrator to set `PAPER_PUBLIC_URL` or `--public-url` and generate a fresh invitation.

連線至公開伺服器時，請使用伺服器發出的完整 HTTPS 邀請網址。該網址的來源也是後續 API 請求的基底位址。若公開伺服器的邀請含有回送位址，請管理員設定 `PAPER_PUBLIC_URL` 或 `--public-url`，再產生新邀請。

### Copy-paste prompt · 可複製的提示

**Copy prompt** fills in the complete one-time URL. If you use this template manually, replace `<registration_url>` with the exact `registration_url` returned by the invitation API, and match the invited username and role.

**Copy prompt** 會自動填入完整的一次性註冊網址。若手動使用範本，請將 `<registration_url>` 替換為邀請 API 回傳的完整 `registration_url`，並填入邀請指定的帳號名稱與角色。

~~~text
Connect to my Paper Library as reviewer (local AI). Register this agent and verify the connection.

One-time registration URL: <registration_url>
Run the following commands in your own environment. If you can access the Paper Library repository there, install the client from that checkout:
python3 -m pip install ./paper_client

Register and save your identity:
python3 -m paper_client.agent register --username reviewer --identity ~/.paper-library/reviewer.json

Enter the full HTTPS registration URL when prompted, or supply it privately on stdin. The client saves the server URL and generates an Ed25519 private key in the identity file. Keep the identity file and any access tokens out of chat and logs.

Verify your account and read the default API skill:
python3 -m paper_client.agent request --identity ~/.paper-library/reviewer.json /api/account
python3 -m paper_client.agent request --identity ~/.paper-library/reviewer.json /api/skills/default

If the client is unavailable, use an HTTP client with Ed25519 signing. Use the origin from the registration URL for each API request and send Content-Type: application/json for each POST.
1. Generate and retain an Ed25519 key pair. Sign paper-library:register:<invited username>:<registration_path> as ASCII, where registration_path is the path component of the invitation URL. POST the raw public key and signature as unpadded base64url in the JSON fields public_key and signature to the full registration URL.
2. POST {"username":"reviewer"} to /api/ai/challenge. Sign paper-library:login:<returned username>:<challenge> as ASCII. POST username, challenge, and signature as JSON to /api/ai/login. Encode the signature as unpadded base64url.
3. Use the returned access_token as a Bearer token to GET /api/account and /api/skills/default.

Report the connected username and role. Use the saved identity for subsequent API requests.
~~~

For later requests, run `paper_client.agent request` with the same identity. Pass `--json-stdin` and a JSON object on standard input for POST requests. If the connection drops during registration, try `/api/account` using the saved identity first. If the original registration never completed, retry with the same file and an active invitation.

後續請求請使用同一個身分檔案執行 `paper_client.agent request`。POST 請求可加上 `--json-stdin`，並從標準輸入提供 JSON 物件。若註冊途中斷線，先用已儲存的身分查詢 `/api/account`。若註冊尚未完成，請使用原身分檔案與有效邀請重試。

### Register and authenticate over HTTP · 透過 HTTP 註冊與登入

A trusted human can create an invitation from the Account page or with their own application key. Set `PAPER_SERVER_URL` to the origin you use to open the library. Change `role` to `cloud` for a cloud AI account.

受信任人員可在帳號頁發出邀請，也可使用自己的應用程式金鑰呼叫 API。請將 `PAPER_SERVER_URL` 設為開啟論文庫時使用的來源。若要註冊雲端 AI，請將 `role` 改為 `cloud`。

```sh
PAPER_SERVER_URL='https://papers.example.org'
curl -fsS "${PAPER_SERVER_URL}/api/ai/invitations" \
  -H "Authorization: Bearer $PAPER_APP_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"username":"reviewer","role":"local"}'
```

The response includes the full `registration_url`, its `registration_path`, `username`, `role`, and `expires_in`. Send `registration_url` to the intended agent. An agent with its own HTTP client can follow these steps from its own machine. Resolve each relative API path against the origin in `registration_url`.

1. Generate an Ed25519 key pair and retain the private key. Sign the ASCII string `paper-library:register:<invited username>:<registration_path>` using the exact username and path returned by the server. POST `{"public_key":"…","signature":"…"}` to the registration URL. Encode the raw 32-byte public key and 64-byte signature as unpadded base64url. A successful request creates the account with the invitation's role and consumes the URL.
2. POST `{"username":"reviewer"}` to `/api/ai/challenge`. Use the returned `username` and `challenge` to sign the ASCII string `paper-library:login:<username>:<challenge>`.
3. POST `{"username":"…","challenge":"…","signature":"…"}` to `/api/ai/login`, with the signature again encoded as unpadded base64url. A successful sign-in consumes the challenge. A challenge expires after two minutes.
4. Send `Authorization: Bearer <access_token>` to `GET /api/account` and subsequent API requests. The access token expires after 15 minutes. Request and sign a fresh challenge to renew it.

Send JSON with `Content-Type: application/json`. Registration, challenge, and login require no existing account session. Access to papers, documents, and review assignments follows the registered account's sharing permissions.

代理應保留 Ed25519 私鑰，並依上述格式簽署註冊路徑，再將公鑰及簽章送至註冊網址。登入時向 `/api/ai/challenge` 取得兩分鐘內有效的一次性挑戰碼，簽署後送至 `/api/ai/login`。公鑰與簽章皆使用不含填充字元的 base64url 編碼。後續請求請在 `Authorization` 標頭中使用回傳的 Bearer 權杖。權杖有效期為 15 分鐘，可透過新的挑戰碼更新。論文、文件和審閱指派的存取權依帳號的分享設定而定。

## Review assignments · 審閱指派

Share a paper, document, or comment thread with the AI account. Choose **Review with AI**, select an eligible AI account, and select **Request review**. The dialog shows the result once the AI responds. The optional comment is visible only to the assigned AI account.

先將論文、文件或留言討論串分享給 AI 帳號。在 **Review with AI** 選取有存取權限的 AI 帳號，再選擇 **Request review**。AI 回覆後，結果會顯示在對話框中。若選擇一併發表留言，該留言僅指派的 AI 帳號可見。

If only one account can access the selected source, the dialog selects it automatically. For a thread, the account needs access to the selected comment, its parents, and any linked sources. The review stays queued until that account’s worker picks it up.

若只有一個 AI 帳號可讀取所選來源，系統會自動選取該帳號。審閱討論串時，帳號需要讀取所選留言、上層留言及引用來源的權限。請求會排隊等待該帳號的用戶端接收。

Install the workstation client with `python3 -m pip install ./paper_client`. Start one worker per AI account with `--agent-identity` and the file created during registration. It uses the saved server URL and renews its access token automatically. Existing accounts can use an application key with `--server-url https://papers.example.org` or a loopback `--port`.

使用 `python3 -m pip install ./paper_client` 安裝工作站用戶端。每個 AI 帳號各啟動一個背景用戶端，透過 `--agent-identity` 指定註冊時建立的檔案。用戶端會使用檔案中的伺服器網址，並自動更新存取權杖。既有帳號可使用應用程式金鑰，透過 `--server-url` 指定公開 HTTPS 網址，或用 `--port` 指定回送連接埠。

| Mode | Setup | 設定方式 |
| --- | --- | --- |
| Local AI · 本機 AI | Install `llama-completion` and use a GGUF model. PDF review needs `pdftotext` on the workstation. | 安裝 `llama-completion` 並使用 GGUF 模型。審閱 PDF 時，工作站須備有 `pdftotext`。 |
| Cloud AI · 雲端 AI | Set `PAPER_AI_CLOUD_URL` to your provider's HTTPS Chat Completions endpoint and `PAPER_AI_CLOUD_MODEL` to its model ID. The worker asks for confirmation before sending each review. | 將 `PAPER_AI_CLOUD_URL` 設為供應商的 HTTPS Chat Completions 端點，並將 `PAPER_AI_CLOUD_MODEL` 設為模型 ID。用戶端在每次送出審閱資料前都會要求確認。 |

```sh
python3 -m paper_client --watch --agent-identity ~/.paper-library/reviewer.json --model /path/to/model.gguf
# Cloud worker / 雲端用戶端
python3 -m paper_client --watch --agent-identity ~/.paper-library/cloud-reviewer.json --cloud
```

An AI client can also follow **Skills → Default API skill** to read and complete assignments directly over HTTP. The skill is built in and available through `GET /api/skills/default`. For additional review guidance, add `--skill ID` to the workstation command.

AI 用戶端也可依 **Skills → Default API skill** 的指引，直接以 HTTP 取得並完成指派。此內建技能可透過 `GET /api/skills/default` 讀取。若要為工作站加入其他審閱指引，可在啟動指令加上 `--skill ID`。

Local and cloud accounts use the same HTTP endpoints with their own bearer credentials. Open `/api/openapi.json` on your library to see request fields and responses. The VS Code extension can edit documents and post comments. [VS Code setup](../vscode-extension/README.md)

本機與雲端 AI 帳號使用同一組 HTTP 端點，並各自使用 Bearer 憑證。可在論文庫的 `/api/openapi.json` 查看請求欄位與回應格式。VS Code 擴充功能可編輯文件與發表留言。 [VS Code 設定](../vscode-extension/README.md)

```sh
curl -fsS -H "Authorization: Bearer $PAPER_APP_KEY" \
  "${PAPER_SERVER_URL}/api/paper-catalog?q=benchmark"
```

## Loopback-only access · 僅限回送連線

For a library reachable only by loopback on a different machine, run the tunnel in the agent's environment. Replace `user@library-host` with your SSH login and host.

若另一台機器上的論文庫僅開放回送連線，請在代理的執行環境建立通道，並將 `user@library-host` 換成實際的 SSH 帳號及主機。

```sh
ssh -N -L 18765:127.0.0.1:8765 user@library-host
```

Keep the tunnel running. Use `http://127.0.0.1:18765` as the origin on the agent's machine and append the original `registration_path` when enrolling. The client saves the forwarded address for future requests.

請維持通道連線。代理端使用 `http://127.0.0.1:18765`，註冊時接上原本的 `registration_path`。用戶端會儲存轉送後的位址供後續請求使用。
