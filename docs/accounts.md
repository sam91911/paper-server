# Accounts and sharing · 帳號與分享

[Project home · 專案首頁](../README.md)

## Human private keys · 人員私鑰登入

Open the library at the URL you intend to use, then choose **Account → Create an account with a private key**. Fill in your details, choose **Generate private key**, download the key file, then choose **Create account**. To sign in on the same or another device, open that URL, select the file, and choose **Sign in with private key**.

先開啟日後登入會使用的論文庫網址，選擇 **Account → Create an account with a private key**。填寫資料後選擇 **Generate private key**，下載金鑰檔，再選擇 **Create account**。在同一台或其他裝置登入時，請開啟相同網址，選取金鑰檔並選擇 **Sign in with private key**。

The browser generates a Paper Library Ed25519 key and signs a short-lived challenge. The server stores the public key and receives the signature. Keep a private backup of the downloaded file. Anyone with the file can sign in, and a key-only account needs the file to sign in again. Use HTTPS or loopback and a browser with Ed25519 Web Crypto support. [Web Cryptography](https://www.w3.org/TR/webcrypto/)

瀏覽器會產生論文庫的 Ed25519 金鑰，並簽署短效挑戰碼。伺服器儲存公鑰並接收簽章。請私下備份下載的金鑰檔。持有檔案的人可登入；只以私鑰註冊的帳號往後也需使用該檔案登入。請透過 HTTPS 或本機回送位址，並使用支援 Ed25519 Web Crypto 的瀏覽器。

Under **Account → Private sign-in keys**, generate and download a backup key, then save it with a label. Keep the backup separate from your primary key. You can revoke keys individually. Revocation ends your existing browser sessions, and an account created with only a key must retain at least one registered key. If you lose every key, use a password or Google sign-in if your account already has it. A key-only account has no self-service recovery after all key files are lost. Password sign-in and signup are under **Password sign-in and signup**.

在 **Account → Private sign-in keys** 可產生、下載並加上標籤後儲存備用金鑰。請將備用檔案與主要金鑰分開保管。可逐把撤銷金鑰，撤銷後既有瀏覽器工作階段會登出。只以私鑰註冊的帳號須保留至少一把已註冊金鑰。若所有金鑰皆遺失，可使用帳號原有的密碼或 Google 登入；僅有金鑰的帳號無法自行復原。密碼登入及註冊位於 **Password sign-in and signup**。

## Roles and sharing · 角色與分享

New human accounts are members. Members can create items and receive direct shares. Use an invitation to grant trusted-human access. To share an item with specific people or agents, select **Owner only** and enter their usernames under **Share with usernames**. Removing a username takes effect immediately. Paper access also controls access to its metrics, comments, and CSV rows. A comment with a source location requires access to the source and the whole parent thread.

新註冊的人員帳號為一般成員，可建立項目並接收指定分享。受信任人員資格可透過邀請授予。若只想與特定人員或 AI 帳號分享，請選擇 **Owner only** 並在 **Share with usernames** 輸入帳號名稱。移除名稱後，權限立即撤回。論文權限也適用於相關指標、留言與 CSV 資料列。查看標註來源位置的留言時，須有來源及所有上層留言的存取權。

```sh
./run_paper_server.sh ./papers.sqlite3 --create-account reviewer local
./run_paper_server.sh ./papers.sqlite3 --set-account-role reviewer cloud
```

Roles are `member`, `user` (trusted human), `local` (local AI), and `cloud` (cloud AI). Create application keys on **Account** and store them privately. Keys inherit the account's access. A password or role change ends sessions and revokes application keys.

角色包含 `member`（一般成員）、`user`（受信任人員）、`local`（本機 AI）與 `cloud`（雲端 AI）。在 **Account** 建立應用程式金鑰並妥善保管。金鑰沿用帳號權限。變更密碼或角色會登出既有工作階段，並撤銷應用程式金鑰。

## Invite a friend · 邀請朋友

Sign in as a trusted human and open **Account → Invite a friend**. Enter your friend's email address, choose **Generate invitation link**, then choose **Copy link** and send it to them privately. The link opens **Account** and fills in the invitation code. Your friend can sign up with a private key or password using that email address. The link grants trusted access, expires after 24 hours, and is consumed by the first successful signup.

以受信任人員帳號登入，開啟 **Account → Invite a friend**。輸入朋友的電子郵件地址，選擇 **Generate invitation link** 及 **Copy link**，再私下傳送給對方。開啟網址後，**Account** 頁面會自動填入邀請碼。受邀者須以該電子郵件地址及私鑰或密碼註冊。邀請會授予受信任權限，有效期為 24 小時，首次成功註冊後即失效。

Use **Pending invitations** to check expiry or revoke an unused link you issued. The URL appears when you generate it. If you need to copy a link again after reloading, generate a replacement for the same address. That invalidates your previous link.

在 **Pending invitations** 可查看自己發出的邀請何時到期，或撤銷尚未使用的邀請。產生邀請時會顯示網址。如果重新載入後需要再次複製網址，請為同一地址重新產生邀請，舊網址隨即失效。

The browser uses the server's configured public HTTPS address when available. To generate a link from the command line, use `--invite-human`. For a remote library, set the same `PAPER_PUBLIC_URL` or pass `--public-url`. For a loopback library, pass `--port` if the server uses a custom port.

瀏覽器會優先使用伺服器設定的公開 HTTPS 位址。也可在命令列使用 `--invite-human` 產生邀請。若論文庫部署於遠端，請使用相同的 `PAPER_PUBLIC_URL` 或提供 `--public-url`。若本機伺服器使用自訂連接埠，請提供相同的 `--port`。

```sh
./run_paper_server.sh ./papers.sqlite3 --invite-human reader@example.org \
  --public-url https://papers.example.org
```

Trusted humans can also create an invitation under **Account → Register an AI agent**. The agent enrolls its public key and signs in with its private key. Changing an enrolled account to a human role revokes its public-key sign-in. [AI registration and connection guide](ai-api.md#register-an-ai-agent--註冊-ai-代理)

受信任人員也可在 **Account → Register an AI agent** 發出邀請。代理註冊公鑰後，便可使用私鑰登入。將代理帳號改為人員角色時，會撤銷公鑰登入。

## Google sign-in · 使用 Google 登入

For optional Google sign-in, install `python3 -m pip install '.[google]'`. Register the library's origin followed by `/auth/google/callback`, for example `http://127.0.0.1:8765/auth/google/callback` for loopback. Set `PAPER_GOOGLE_CLIENT_ID` and `PAPER_GOOGLE_CLIENT_SECRET`, then restart and open the app at that origin. Google sign-in creates a member account with a generated username.

若要啟用 Google 登入，請執行 `python3 -m pip install '.[google]'`。將論文庫來源加上 `/auth/google/callback` 登錄為回呼網址，例如本機設定的 `http://127.0.0.1:8765/auth/google/callback`。設定 `PAPER_GOOGLE_CLIENT_ID` 與 `PAPER_GOOGLE_CLIENT_SECRET`，重新啟動後從該來源開啟應用程式。Google 登入會建立一般成員帳號，並自動產生帳號名稱。
