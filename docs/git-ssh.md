# Git over SSH · 透過 SSH 使用 Git

Paper Library can use the same Ed25519 key you already use for human or agent sign-in. Export it locally in OpenSSH format. The server checks the registered public key and the repository's sharing permissions. The private key stays on your machine.

Paper Library 可使用人員或代理登入時原有的 Ed25519 金鑰。請在本機匯出為 OpenSSH 格式。伺服器會檢查已註冊的公開金鑰與儲存庫分享權限，私鑰保留在自己的電腦。

## Clone and push · 複製及推送

Install the Paper Library client on the workstation and get the SSH host, username, port, and host key fingerprint from your administrator. Replace the sample origin and IDs below.

請在工作站安裝 Paper Library 用戶端，並向管理員取得 SSH 主機、帳號、連接埠及主機金鑰指紋。將下方的範例網址與編號改為實際值。

```sh
python3 -m paper_client.ssh_key ~/paper-library-identity.json --out ~/.ssh/paper-library
# Optional for an interactive workstation. Add a passphrase to the exported copy.
ssh-keygen -p -f ~/.ssh/paper-library

export GIT_SSH_COMMAND='ssh -i ~/.ssh/paper-library -o IdentitiesOnly=yes'
git clone ssh://paper-library@papers.example.org:2222/git/documents/42.git
git clone --branch source ssh://paper-library@papers.example.org:2222/git/experiments/7.git
# Commit changes in either checkout, then run git push in that checkout.
```

Use your downloaded human identity file or your agent's enrolled identity file as the input. The export creates a new mode-0600 file and refuses to overwrite an existing file. An encrypted export can be loaded into `ssh-agent`. The registered key must identify one active account in this workspace. Removing or replacing the key, or disabling the account, revokes SSH access.

輸入檔可使用已下載的人員私鑰檔或代理的已註冊身分檔。匯出會建立權限為 0600 的新檔案，並拒絕覆寫既有檔案。加密後可載入 `ssh-agent`。註冊金鑰須在此工作區對應至一個有效帳號。移除或替換金鑰、停用帳號都會撤銷 SSH 存取。

Document pushes go to `main`. Experiment source pushes go to `source`. For artifact pointers in an SSH checkout, use the normal artifact helper with the library's HTTPS origin and an application key, or with an enrolled agent identity. [Git branches and artifacts](git-and-discussions.md)

文件推送至 `main`，實驗原始碼推送至 `source`。SSH 工作副本的產出指標檔仍可透過一般產出工具使用，提供論文庫 HTTPS 網址與應用程式金鑰，或使用已註冊代理身分。

## Enable the Git-only SSH listener · 啟用 Git 專用 SSH 服務

Use a dedicated OpenSSH configuration with its own port and the Unix account that already runs the workspace. That account needs an executable shell such as `/bin/sh` so OpenSSH can invoke the forced Git command. The standalone config accepts registered Ed25519 keys and disables terminal sessions and forwarding. OpenSSH requires the `AuthorizedKeysCommand` executable and its parent directories to be owned by root and writable only by root. Keep the installed app and SSH configuration under the same ownership.

使用有獨立連接埠的專用 OpenSSH 設定，並採用執行工作區的 Unix 服務帳號。該帳號須有可執行的 shell（例如 `/bin/sh`），供 OpenSSH 啟動強制執行的 Git 指令。獨立設定接受已註冊的 Ed25519 金鑰，並停用終端機及轉送。OpenSSH 要求 `AuthorizedKeysCommand` 的執行檔及其上層目錄由 root 擁有且僅能由 root 寫入。已安裝的應用程式與 SSH 設定也應採用相同的權限。

Create `/etc/paper-library-git.toml` with the same database and storage quota as the web service. For example:

建立 `/etc/paper-library-git.toml`，使用與網頁服務相同的資料庫及儲存配額。例如：

```toml
database = "/var/lib/paper-library/library.sqlite3"
storage_quota_mib = 10240
```

For PostgreSQL use `postgres_url` and an absolute `pdf_dir` instead of `database`. Give the TOML file mode 0640 and ownership `root:paper-library`. Start the web server once to apply migrations and ensure the existing workspace is ready.

使用 PostgreSQL 時，以 `postgres_url` 及絕對路徑 `pdf_dir` 取代 `database`。將 TOML 檔設為 0640，擁有者為 `root:paper-library`。先啟動網頁服務一次，套用資料庫移轉並確認工作區可用。

Copy the [OpenSSH configuration](../deploy/sshd-paper-library.conf) to `/etc/ssh/sshd_config_paper_library` and the [service](../deploy/paper-library-git.service) to `/etc/systemd/system/paper-library-git.service`. Configure the service account, port, and host key. Then run:

將 [OpenSSH 設定](../deploy/sshd-paper-library.conf) 複製到 `/etc/ssh/sshd_config_paper_library`，並將 [服務檔](../deploy/paper-library-git.service) 複製到 `/etc/systemd/system/paper-library-git.service`。設定服務帳號、連接埠與主機金鑰後執行：

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now paper-library-git.service
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Publish the SSH port alongside the web origin and share the host key fingerprint. Use a different Git SSH listener and config for each isolated workspace. [OpenSSH configuration documentation](https://man.openbsd.org/sshd_config)

提供 SSH 連接埠、網頁網址與主機金鑰指紋。每個隔離工作區應有各自的 Git SSH 監聽服務及設定。

## Project repositories and HTTPS tokens · 專案儲存庫及 HTTPS Token

A project owner can grant read or write access to enrolled people and agents from **Projects → Collaborators**. Use the same SSH key export above and replace the path with the project ID:

```sh
git clone ssh://paper-library@papers.example.org:2222/git/projects/42.git
git clone --branch experiment/7 ssh://paper-library@papers.example.org:2222/git/projects/42.git
```

For HTTPS, open **Projects → Git tokens**. Select one project, experiment, or document, choose read or write access and a 1–90 day expiry, then copy the token. Use your Library username and enter the token as the Git password. Tokens can be revoked from the same panel. A token is scoped to one repository and follows the current permissions of the account that issued it. Use a separate token per integration.

Agents can issue a token using their enrolled identity. For example:

```sh
python3 -m paper_client.agent request --identity /absolute/path/to/agent.json /api/git-tokens --json-stdin <<'JSON'
{"action":"create","kind":"projects","resource_id":42,"access":"write","days":7}
JSON
```

Save the `token` field privately. To list metadata, call `GET /api/git-tokens`. To revoke a token, send `{"action":"revoke","id":"<token-id>"}` to the same route. Git tokens also work in a Bearer header for Git HTTPS. The secret is returned at issuance only.

人員與代理可建立只適用於單一儲存庫的 Token，選擇僅讀取或可推送，並設定到期日。HTTPS Git 要求密碼時，輸入 Token。SSH 使用各自已註冊的 Ed25519 金鑰，存取權限會依專案分享設定判定。
