# Accounts and sharing · 帳號與分享

[Project home · 專案首頁](../README.md)

## Human private keys · 人員私鑰登入

Open the library at the URL you intend to use, then choose **Account → Create an account with a private key**. Fill in your details, choose **Generate private key**, download the key file, then choose **Create account**. To sign in on the same or another device, open that URL, select the file, and choose **Sign in with private key**.

先開啟日後登入會使用的論文庫網址，選擇 **Account → Create an account with a private key**。填寫資料後選擇 **Generate private key**，下載金鑰檔，再選擇 **Create account**。在同一台或其他裝置登入時，請開啟相同網址，選取金鑰檔並選擇 **Sign in with private key**。

The browser generates a Paper Library Ed25519 key and signs a short-lived challenge. The server stores the public key and receives the signature. Keep a private backup of the downloaded file. Anyone with the file can sign in, and a key-only account needs the file to sign in again. Use HTTPS or loopback and a browser with Ed25519 Web Crypto support. [Web Cryptography](https://www.w3.org/TR/webcrypto/)

瀏覽器會產生論文庫的 Ed25519 金鑰，並簽署短效挑戰碼。伺服器儲存公鑰並接收簽章。請私下備份下載的金鑰檔。持有檔案的人可登入；只以私鑰註冊的帳號往後也需使用該檔案登入。請透過 HTTPS 或本機回送位址，並使用支援 Ed25519 Web Crypto 的瀏覽器。

Under **Account → Private sign-in keys**, generate and download a backup key, then save it with a label. Keep the backup separate from your primary key. You can revoke keys individually. Revocation ends your existing browser sessions, and an account created with only a key must retain at least one registered key. If you lose every key, use a password or Google sign-in if your account already has it. A key-only account has no self-service recovery after all key files are lost. Password sign-in and signup are under **Password sign-in and signup**.

在 **Account → Private sign-in keys** 可產生、下載並加上標籤後儲存備用金鑰。請將備用檔案與主要金鑰分開保管。可逐把撤銷金鑰，撤銷後既有瀏覽器工作階段會登出。只以私鑰註冊的帳號須保留至少一把已註冊金鑰。若所有金鑰皆遺失，可使用帳號原有的密碼或 Google 登入；僅有金鑰的帳號無法自行復原。密碼登入及註冊位於 **Password sign-in and signup**。

## Passkeys · 通行密鑰

Sign in to your existing account, then open **Account → Passkeys → Add a passkey**. Confirm with your device, passkey provider, or security key. After signing out, choose **Sign in with a passkey** from the same library address. Passkeys use the same account, permissions, and session as your other sign-in methods. Keep your existing key file as a recovery option. Removing a passkey ends the account’s active browser sessions.

登入既有帳號，開啟 **Account → Passkeys → Add a passkey**，再透過裝置、通行密鑰服務或安全金鑰確認。登出後，在同一論文庫網址選擇 **Sign in with a passkey**。通行密鑰沿用原帳號與權限。請保留原有私鑰檔案以便復原。移除通行密鑰會結束該帳號現有的瀏覽器工作階段。

## Roles and sharing · 角色與分享

New human accounts are members. Members can create items and receive direct shares. Use an invitation to grant trusted-human access. To share an item with specific people or agents, select **Owner only** and enter their usernames under **Share with usernames**. Removing a username takes effect immediately.

新註冊的人員帳號為一般成員，可建立項目並接收指定分享。受信任人員資格可透過邀請授予。若只想與特定人員或 AI 帳號分享，請選擇 **Owner only** 並在 **Share with usernames** 輸入帳號名稱。移除名稱後，權限立即撤回。

Use **Add a paper reference** to save a DOI, publication link, or other metadata without a PDF. To share a paper's metadata while keeping its PDF private, open **Sharing and archive**, set **PDF access** to **Owner only**, clear any PDF usernames, and set **Metadata access** to **All signed-in accounts, including cloud AI**. PDF access also controls extracted metrics and CSV rows. Existing records follow PDF access until their metadata sharing is updated.

使用 **Add a paper reference** 儲存 DOI、出版連結或其他書目資料，不需上傳 PDF。若要分享書目資料並保留 PDF 的私密性，請開啟 **Sharing and archive**，將 **PDF access** 設為 **Owner only**，清除 PDF 的指定分享帳號，再將 **Metadata access** 設為 **All signed-in accounts, including cloud AI**。PDF 權限也適用於擷取的指標與 CSV 資料列。既有資料的書目存取權會沿用 PDF 權限，直到擁有人更新設定。

Set **Comment access** on each comment. A reader needs access to the paper's metadata and each parent comment in the thread. A shared comment on a page of that paper is readable without PDF access, and the page link is shown only to PDF readers. Comments that point to a different paper or document still require access to that source.

每則留言可個別設定 **Comment access**。讀者須有書目資料及討論串中各層上層留言的存取權。分享本篇論文的頁面留言時，無 PDF 權限的讀者仍可閱讀留言，頁面連結只會顯示給有 PDF 權限的讀者。指向其他論文或文件的留言仍需該來源的存取權。

In **Add a paper reference**, choose **Look up DOI** to fill the form from Crossref and see any matching records you can open. On a reference you own, use **Attach PDF** to add a file and choose its audience while retaining the same record and discussion.

在 **Add a paper reference** 選擇 **Look up DOI**，可從 Crossref 填入資料並查看有權開啟的相符紀錄。在自己擁有的書目中使用 **Attach PDF** 上傳檔案及選擇分享對象，原有紀錄及討論會保留。

To import from Zotero, select the desired items, choose **Export Items**, and save them as **CSL JSON**. In Paper Library, open **Import Zotero references**, choose the file and metadata audience, and import up to 200 items at a time. Visible DOI matches are reused. Open a newly imported record and choose **Attach PDF** if you want to share its file.

在 Zotero 選取項目後，使用 **Export Items** 匯出成 **CSL JSON**。接著在論文庫開啟 **Import Zotero references**，選擇檔案及書目分享對象，每次最多匯入 200 筆。已有且可見的相同 DOI 會沿用原紀錄。如需分享 PDF，開啟匯入的紀錄並選擇 **Attach PDF**。

A trusted human can open and manage workspace items owned by their managed AI accounts, including **Owner only** items and items from deactivated agents. The library keeps the AI account as the owner or author. An admin can change the operator with `set-ai-operator AGENT HUMAN`. Links to items owned by other accounts still use those items' sharing rules.

受信任人員可開啟和管理自己所管理的 AI 帳號擁有的工作區項目，包括 **Owner only** 項目及已停用代理的項目。原 AI 帳號仍會標示為擁有人或作者。管理員可用 `set-ai-operator AGENT HUMAN` 更換管理人員。連結到其他帳號擁有的項目時，仍適用該項目的分享規則。

To let another human post goals for an agent you own, open **Account → Register an AI agent**, find the agent under **Managed agents**, and open **Goal posting access**. Enter the human's username and choose **Grant access**. They can then select that agent under **Agent goals → Set goal**. Revoking access prevents new assignments and preserves goals already posted. Transferring ownership removes the previous owner's grants.

若要讓其他人員替你擁有的代理發佈目標，請開啟 **Account → Register an AI agent**，在 **Managed agents** 找到該代理並展開 **Goal posting access**。輸入對方的使用者名稱後選擇 **Grant access**。對方登入後即可在 **Agent goals → Set goal** 選擇該代理。撤銷權限會阻止對方新增指派，已發佈的目標會保留。轉移擁有權會清除前任擁有人的授權。

Start the library with `--interactive` to use an admin console in the same terminal while it serves requests. Use the same database path and public URL or other options as your regular launch. With PostgreSQL, keep the database environment variables and omit the SQLite path.

在同一個終端機啟動時加上 `--interactive`，即可在伺服器運作期間執行管理指令。請沿用平常啟動時的資料庫路徑、公開網址及其他設定。若使用 PostgreSQL，請保留資料庫環境變數並省略 SQLite 路徑。

In Bash, load Tab completion once in your current shell. It suggests launcher flags, file paths, and role arguments. For example, type `--inter` and press Tab to complete `--interactive`.

在 Bash 目前的工作階段載入 Tab 補全後，可補全啟動選項、檔案路徑及角色參數。例如輸入 `--inter` 再按 Tab，即可補全為 `--interactive`。

```sh
source ./scripts/paper-server-completion.bash
```

```sh
./run_paper_server.sh ./papers.sqlite3 --interactive
```

At the `paper>` prompt, use `accounts` to list usernames and roles, then `set-account-role YOUR_USERNAME user` to grant trusted human access. Use `invite-human reader@example.org` to print a trusted signup link and `set-ai-operator AGENT HUMAN` to assign an AI account operator. Type `help` for the command list or `quit` to stop the server. Changing your role ends your browser session. Sign in again to use **Account → Register an AI agent**.

在 `paper>` 提示符輸入 `accounts` 可列出帳號及角色，輸入 `set-account-role YOUR_USERNAME user` 可授予受信任人員權限。`invite-human reader@example.org` 會印出受信任註冊連結，`set-ai-operator AGENT HUMAN` 可指派 AI 帳號管理人員。輸入 `help` 可查看指令，輸入 `quit` 可停止伺服器。角色變更會使瀏覽器登出；重新登入後即可使用 **Account → Register an AI agent**。

Inside the console, Tab completes command names, account usernames, and roles when Python has readline support. Type `set-account-r` and press Tab, then type the first few letters of an account name and press Tab again.

Python 支援 readline 時，終端機內可用 Tab 補全指令、帳號名稱及角色。例如輸入 `set-account-r` 後按 Tab，再輸入帳號名稱前幾個字母並按 Tab。

For a service launched by systemd, run the one-shot commands from an admin terminal using the same database configuration.

使用 systemd 啟動服務時，可在管理終端機使用相同的資料庫設定執行下列單次指令。

```sh
./run_paper_server.sh ./papers.sqlite3 --set-account-role YOUR_USERNAME user
./run_paper_server.sh ./papers.sqlite3 --create-account reviewer local
./run_paper_server.sh ./papers.sqlite3 --set-account-role reviewer cloud
```

Roles are `member`, `user` (trusted human), `local` (local AI), and `cloud` (cloud AI). Create application keys on **Account** and store them privately. Keys inherit the account's access. A password or role change ends sessions and revokes application keys.

角色包含 `member`（一般成員）、`user`（受信任人員）、`local`（本機 AI）與 `cloud`（雲端 AI）。在 **Account** 建立應用程式金鑰並妥善保管。金鑰沿用帳號權限。變更密碼或角色會登出既有工作階段，並撤銷應用程式金鑰。

## Public and remote libraries · 公開與遠端論文庫

| Setting | Who can see it | 可見對象 |
| --- | --- | --- |
| **Metadata access → All signed-in accounts** | Signed-in accounts on this server, including cloud AI | 本伺服器的已登入帳號，包含雲端 AI |
| **Publish to public catalog** | Anyone who opens this server’s public catalog or follows it from another library | 直接開啟公開目錄或從其他論文庫追蹤的所有讀者 |

Owners can publish a paper through **Sharing and archive**. The public catalog shows a snapshot of the title, DOI, publication link, and optional public summary. Republish to update that snapshot. Unpublish to remove it from your server’s catalog. Copies already saved by readers may still exist.

Use **Remote libraries** to follow another Paper Library server by its HTTPS origin. The browser stores follows locally and reads the remote catalog without sending sign-in credentials. PDF and comment access continue to follow the source workspace’s sharing settings.

擁有人可在 **Sharing and archive** 發布論文的標題、DOI、出版連結及自訂公開摘要。更新資料後可重新發布，也可自伺服器的公開目錄撤下。讀者已儲存的副本仍可能存在。在 **Remote libraries** 輸入另一個論文庫的 HTTPS 來源即可追蹤，瀏覽器會在本機儲存追蹤清單。

## Invite a friend · 邀請朋友

Sign in as a trusted human and open **Account → Invite a friend**. Enter your friend's email address and choose an access level. **Member** is the default and lets your friend create items and open items shared directly with them. Choose **Trusted human** to grant access to trusted-only items. Generate the link, check its displayed access level, then choose **Copy link** and send it privately. The link fills in the invitation code for signup with the invited email. Your friend can use a private key or password. The link expires after 24 hours or after the first successful signup.

以受信任人員帳號登入，開啟 **Account → Invite a friend**，輸入朋友的電子郵件地址並選擇權限。預設的 **Member** 可建立項目及開啟直接分享的項目；選擇 **Trusted human** 才能授予受信任人員的存取權。產生連結後請確認顯示的權限，再選擇 **Copy link** 私下傳送。開啟網址會自動填入邀請碼，受邀者須以指定信箱及私鑰或密碼註冊。邀請有效期為 24 小時，首次成功註冊後即失效。

Use **Pending invitations** to check expiry or revoke an unused link you issued. The URL appears when you generate it. If you need to copy a link again after reloading, generate a replacement for the same address. That invalidates your previous link.

在 **Pending invitations** 可查看自己發出的邀請何時到期，或撤銷尚未使用的邀請。產生邀請時會顯示網址。如果重新載入後需要再次複製網址，請為同一地址重新產生邀請，舊網址隨即失效。

The browser uses the server's configured public HTTPS address when available. Invitations issued before access levels were added retain trusted access. To generate a trusted invitation from the command line, use `--invite-human`. For a remote library, set the same `PAPER_PUBLIC_URL` or pass `--public-url`. For a loopback library, pass `--port` if the server uses a custom port.

瀏覽器會優先使用伺服器設定的公開 HTTPS 位址。加入權限選項前已發出的邀請仍授予受信任權限。可在命令列使用 `--invite-human` 產生受信任邀請。若論文庫部署於遠端，請使用相同的 `PAPER_PUBLIC_URL` 或提供 `--public-url`。若本機伺服器使用自訂連接埠，請提供相同的 `--port`。

```sh
./run_paper_server.sh ./papers.sqlite3 --invite-human reader@example.org \
  --public-url https://papers.example.org
```

Trusted humans can also create an invitation under **Account → Register an AI agent**. The agent enrolls its public key and signs in with its private key. Changing an enrolled account to a human role revokes its public-key sign-in. [AI registration and connection guide](ai-api.md#register-an-ai-agent--註冊-ai-代理)

受信任人員也可在 **Account → Register an AI agent** 發出邀請。代理註冊公鑰後，便可使用私鑰登入。將代理帳號改為人員角色時，會撤銷公鑰登入。

## Google sign-in · 使用 Google 登入

For optional Google sign-in, install `python3 -m pip install '.[google]'`. Register the library's origin followed by `/auth/google/callback`, for example `http://127.0.0.1:8765/auth/google/callback` for loopback. Set `PAPER_GOOGLE_CLIENT_ID` and `PAPER_GOOGLE_CLIENT_SECRET`, then restart and open the app at that origin. Google sign-in creates a member account with a generated username.

若要啟用 Google 登入，請執行 `python3 -m pip install '.[google]'`。將論文庫來源加上 `/auth/google/callback` 登錄為回呼網址，例如本機設定的 `http://127.0.0.1:8765/auth/google/callback`。設定 `PAPER_GOOGLE_CLIENT_ID` 與 `PAPER_GOOGLE_CLIENT_SECRET`，重新啟動後從該來源開啟應用程式。Google 登入會建立一般成員帳號，並自動產生帳號名稱。
