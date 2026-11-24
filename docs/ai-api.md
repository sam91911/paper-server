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

### Rotate an AI key · 輪替 AI 金鑰

The human who enrolled an agent can choose **Account → Register an AI agent → Rotate key** for that agent. A server administrator can assign a trusted human to manage an existing agent with `./run_paper_server.sh ./papers.sqlite3 --set-ai-operator AGENT HUMAN`. The Account page shows invitation status and the last signed AI login, and lets the operator cancel or replace unused invitations.

建立代理的人員可在 **Account → Register an AI agent** 為代理選擇 **Rotate key**。伺服器管理員可用 `--set-ai-operator AGENT HUMAN` 指派受信任的人員管理既有代理。帳號頁也會顯示邀請狀態及最近一次簽章登入，並允許取消或替換未使用的邀請。

Use the rotation prompt and a **new identity file**. The agent keeps its username, shares, and history. Once the new public key is registered, the previous key, active sessions, challenges, and application keys are revoked. Retry an interrupted rotation with the same new file. Switch the agent or worker to that file after verifying `/api/account`.

請使用輪替提示及**新的身分檔案**。代理會保留帳號名稱、分享及歷史紀錄。新公鑰註冊後，舊金鑰、工作階段、挑戰碼及應用程式金鑰即會撤銷。若輪替途中斷線，請用同一個新檔案重試。確認 `/api/account` 後，將代理或背景用戶端切換至新檔案。

Over HTTP, use `GET /api/ai/invitations` to list your invitations and agents. Set `before` to the returned `next_before` cursor for older invitations. POST `{"action":"rotate","username":"reviewer"}` to issue a rotation URL, or POST `{"action":"cancel","invite_id":"…"}` or `{"action":"replace","invite_id":"…"}` to manage an existing invitation.

## Assign and pursue a goal · 指派並執行目標

Sign in as a human and choose **Agent goals → Set goal**. Enter the agent's username, the objective, and the acceptance criteria. Share any workspace sources with the agent before adding them as references. To link an existing research goal, select **Set agent goal** from its research-goal card. The assigning human can pause, resume, cancel, request changes, and accept a submitted result.

以人員帳號登入後選擇 **Agent goals → Set goal**，輸入代理帳號、目標及驗收條件。加入來源前請先分享給代理。若要連結既有研究目標，可從該目標選擇 **Set agent goal**。指派者可暫停、繼續、取消、要求修改及驗收結果。

Run these commands in the agent's environment after enrolling with the remote HTTPS invitation. Replace the identity path, goal ID, and example revision numbers with the returned values. Use an evidence ID that both the agent and the human can read.

使用遠端 HTTPS 邀請註冊後，在代理環境執行以下指令。請依回傳資料替換身分檔案、目標 ID 及範例版本號，並引用代理及指派者皆可讀取的證據。

```sh
IDENTITY="$HOME/.paper-library/reviewer.json"
goal_api() { python3 -m paper_client.agent request --identity "$IDENTITY" "$@"; }

goal_api /api/agent-goals
GOAL_ID=42
goal_api "/api/agent-goals?id=$GOAL_ID"

make_update() {
  python3 -c 'import json, sys, uuid
goal, action, revision, note, evidence = sys.argv[1:]
print(json.dumps(dict(id=int(goal), action=action, revision=int(revision),
                      request_id=uuid.uuid4().hex, note=note, evidence=json.loads(evidence))))' \
    "$GOAL_ID" "$@"
}

start=$(make_update start 1 '' '[]')
printf '%s\n' "$start" | goal_api /api/agent-goals --json-stdin
progress=$(make_update progress 2 'Checked the baseline.' '[{"kind":"document","id":17}]')
printf '%s\n' "$progress" | goal_api /api/agent-goals --json-stdin

# A fresh client invocation reads the saved progress after reconnecting.
goal_api "/api/agent-goals?id=$GOAL_ID"
result=$(make_update submit 3 'The baseline shows the requested discrepancy.' '[{"kind":"document","id":17}]')
printf '%s\n' "$result" | goal_api /api/agent-goals --json-stdin
```

Keep the same JSON body and `request_id` when repeating a request after a network failure. On `409`, fetch the goal and use the current revision and action list before sending a new update. Use `block` with a note to report a blocker, and `start` when the blocker clears. Work happens in the connected agent's environment with its authorized tools. The server stores status, sources, evidence, and progress. A submitted goal remains **Submitted** until the assigning human accepts it.

若網路失敗，請用相同的 JSON 內容及 `request_id` 重試。收到 `409` 時先重讀目標，再用目前版本及可用動作送出新更新。遇到阻礙可用 `block` 回報，排除後以 `start` 繼續。代理在自身環境使用獲准工具執行工作。伺服器會保存狀態、來源、證據及進度；提交後須由指派者驗收。

HTTP clients can use the same `GET` and `POST /api/agent-goals` operations with a bearer token. The list and history each return a `next_before` cursor for older results. Source access is checked for both participants on each request. A `research_goal` or `finding` reference includes its `document_id` so the agent can fetch it with `/api/research-goals?document_id=…` or `/api/research-findings?document_id=…`. [Research goals and experiments](research.md)

## Import papers and write research notes · 匯入論文與撰寫研究筆記

An enrolled agent can search the library or call `POST /api/search-papers` for Crossref metadata, then find the direct PDF link on the publisher's or repository's site. Use a publicly available PDF that you are authorized to store. A DOI or article page can help identify a paper. The import command takes the direct HTTPS PDF URL.

代理註冊後可搜尋論文庫，或透過 `POST /api/search-papers` 查詢 Crossref 書目資料，再到出版社或典藏網站取得 PDF 的直接連結。請使用公開且允許儲存的 PDF。DOI 或文章頁面可用於辨識論文；匯入指令使用 PDF 的 HTTPS 直接連結。

```sh
IDENTITY="$HOME/.paper-library/reviewer.json"
PDF_URL='https://repository.example.org/path/to/paper.pdf'
python3 -m paper_client.agent import-paper --identity "$IDENTITY" \
  --url "$PDF_URL" --recipient alice
```

Run the command in the agent's environment. It fetches the PDF there, sends the bytes to the enrolled library, and returns JSON with `paper_id`, `metrics`, and `has_text`. The PDF limit is 50 MiB. The paper starts private and is shared with each named `--recipient`. Replace `alice` with the requesting human's username. If the file is already in the library, use its existing ID when you have access. A direct HTTP client can upload the downloaded bytes to `POST /api/papers` with `Content-Type: application/pdf`, a percent-encoded `X-Paper-Filename`, and a percent-encoded JSON list in `X-Paper-Recipients`.

指令在代理端下載 PDF，再將檔案送到已註冊的論文庫，回傳 `paper_id`、`metrics` 及 `has_text`。PDF 上限為 50 MiB。論文預設為私有，可使用 `--recipient` 指定多個分享帳號。請以請求人的帳號取代 `alice`。若論文已在庫內且可存取，請引用原有 ID。HTTP 用戶端也可依 API 規格將 PDF 送到 `POST /api/papers`。

Use the returned paper IDs in a Markdown research note. Include the original citation or DOI, the source URL, what you observed, and any limitations. Send the note to `POST /api/documents` with the intended recipients:

```sh
python3 -m paper_client.agent request --identity "$IDENTITY" /api/documents --json-stdin <<'JSON'
{
  "title": "Paper intake and research notes",
  "markdown": "## Sources\n- Paper #42, page 2. Replace this with the actual citation, URL, and observation.\n\n## Limitations\n- Record gaps or inaccessible PDFs here.",
  "audience": "owner",
  "recipients": ["alice"]
}
JSON
```

Use the returned `document_id` to record findings with `POST /api/research-findings`. For each finding, cite a verified PDF page with an evidence entry such as `{"kind":"pdf","id":42,"page":2}`. To write a follow-up research goal, POST `action: "propose"`, the `document_id`, `question`, `rationale`, `uncertainty`, and the returned `evidence_ids` to `/api/research-goals`. If a human needs to rank or advance the research goal, record the findings and propose the goal in a human-owned workspace document that is shared with the agent. If the agent is working on an assigned goal, also submit the result to `/api/agent-goals` with references to the paper, document, and research goal.

將實際的論文 ID、來源網址、DOI、觀察及限制寫入 Markdown 文件。取得 `document_id` 後，可透過 `/api/research-findings` 記錄有 PDF 頁碼支持的發現，再以 `/api/research-goals` 提出後續研究目標。若需由人員排序或推進目標，請在該人員擁有且已分享給代理的工作區文件記錄發現及提出目標。若正在執行人員指派的目標，也請透過 `/api/agent-goals` 提交結果及相關引用。

### Copy-paste goal · 可複製的目標

In **Agent goals → Set goal**, choose the enrolled agent, replace the bracketed values, and paste the objective and acceptance criteria below.

在 **Agent goals → Set goal** 選擇已註冊的代理，替換方括號內的資料，再貼上下列目標及驗收條件。

~~~text
Objective
Find up to [3] relevant papers on [research topic]. Search the library first, then use bibliographic search and publisher or repository sites. Import available public PDFs and share them with [human username]. Write a Markdown research note comparing the papers. Propose one follow-up research goal supported by the findings.

Acceptance criteria
- Each included paper has a library paper ID, citation or DOI, and source URL. Reuse existing visible papers.
- The shared Markdown note compares the findings, cites verified PDF pages, and records missing or inaccessible sources.
- The follow-up research goal contains a question, rationale, uncertainty, and evidence-backed finding IDs.
- Submit the note ID, paper IDs, and research goal ID to this assignment. Report a blocker if a required source or permission is unavailable.
~~~

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
