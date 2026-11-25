# Isolated lab workspaces · 隔離的實驗室工作區

[Deployment guide · 部署指南](deployment.md)

Give each lab a separate HTTPS hostname, loopback port, service account, and library database. Each library has its own human accounts, AI agents, papers, goals, and artifacts. Accounts can use the same username in different labs. Sign in at the intended hostname and generate invitations there.

為每個實驗室設定獨立的 HTTPS 主機名、本機迴路連接埠、服務帳號及資料庫。各資料庫分別管理人員、AI 代理、論文、目標及產出檔。不同實驗室可使用相同帳號名稱。請於目標工作區登入並產生邀請。

## Start two workspaces · 啟動兩個工作區

Install the app and Poppler as in the [single-server deployment guide](deployment.md). The systemd template assumes the app is installed at `/opt/paper-library/.venv`. Use a short lowercase workspace name such as `alpha` or `beta`.

安裝步驟與[單一伺服器部署](deployment.md)相同。systemd 範本假設程式位於 `/opt/paper-library/.venv`。工作區名稱請使用簡短的小寫名稱，例如 `alpha` 或 `beta`。

```sh
sudo useradd --system --user-group --no-create-home paper-alpha
sudo useradd --system --user-group --no-create-home paper-beta
sudo install -d -m 0750 /etc/paper-library/workspaces
sudo install -m 0644 deploy/paper-workspace@.service /etc/systemd/system/
```

Create a root-owned, mode-0600 environment file for each instance. Set each HTTPS hostname to match the reverse proxy and each port to a different loopback port.

為每個執行個體建立 root 擁有、權限為 0600 的環境檔。設定與反向代理相符的 HTTPS 主機名，並使用不同的本機迴路連接埠。

`/etc/paper-library/workspaces/alpha.env`

```ini
PAPER_PUBLIC_URL=https://alpha.papers.example.org
PAPER_PORT=8771
PAPER_STORAGE_QUOTA_MIB=10240
```

`/etc/paper-library/workspaces/beta.env`

```ini
PAPER_PUBLIC_URL=https://beta.papers.example.org
PAPER_PORT=8772
PAPER_STORAGE_QUOTA_MIB=10240
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now paper-workspace@alpha.service paper-workspace@beta.service
```

With the [release symlink layout](deployment.md#upgrade-while-serving-traffic--不中斷服務升級), reload each workspace to pick up a staged release, for example `sudo systemctl reload paper-workspace@alpha.service`. Check its journal and public health endpoint before reloading the next workspace.

使用上述版本符號連結配置後，可透過 `sudo systemctl reload paper-workspace@alpha.service` 等指令逐一載入新版。確認目前工作區的日誌及公開健康檢查後，再重新載入下一個工作區。

By default, Alpha stores its SQLite database at `/var/lib/paper-library-alpha/papers.sqlite3` and its PDFs beside it in `papers.sqlite3.pdfs`. Beta has a separate state directory. For PostgreSQL, install the extra and set `PAPER_DATABASE_URL` and `PAPER_PDF_DIR` in each environment file. Use a different database and database role per lab, revoke public connection privileges on each lab database, and use a PDF directory within that service's state directory.

Alpha 預設使用 `/var/lib/paper-library-alpha/papers.sqlite3`，PDF 存於同一層的 `papers.sqlite3.pdfs`。Beta 有獨立的狀態目錄。使用 PostgreSQL 時需安裝選用依賴，並為每個工作區設定不同的資料庫、資料庫角色與 PDF 目錄。移除各資料庫的公開連線權限，並將 PDF 存於該工作區的狀態目錄內。

Install [the Nginx workspace example](../deploy/nginx-paper-workspaces.conf) once. Replace the example hostnames and certificate paths. The example expects one certificate valid for both names. Set both DNS records, run `sudo nginx -t`, reload Nginx, and check `/api/health` on each HTTPS hostname. Keep the backend ports private.

[安裝 Nginx 工作區範本](../deploy/nginx-paper-workspaces.conf)，替換主機名及憑證路徑。範本使用一張同時適用於兩個主機名的憑證。設定 DNS 後執行 `sudo nginx -t`，重新載入 Nginx，並檢查各網域的 `/api/health`。後端連接埠維持私有。

## Manage membership and uploads · 管理成員及上傳

For the default SQLite setup, generate the first trusted human invitation as the workspace's service user. Send the printed link to that person. Repeat with Beta's own user, database, and hostname.

使用預設的 SQLite 時，請以該工作區的服務帳號建立第一個受信任人員邀請，並將輸出網址交給對方。Beta 請使用自己的帳號、資料庫及主機名執行同樣步驟。

```sh
sudo -u paper-alpha /opt/paper-library/.venv/bin/python -m paper_app.server \
  --database /var/lib/paper-library-alpha/papers.sqlite3 \
  --public-url https://alpha.papers.example.org --invite-human lead@example.org
```

Trusted humans can invite members, other trusted humans, and AI agents from **Account**. Members can read records shared with them. A private-key or password signup requires a valid workspace invitation. An existing Google identity can still sign in when Google is configured. For PostgreSQL administrative commands, use that workspace's database and PDF environment instead of `--database`.

受信任人員可在 **Account** 邀請成員、其他受信任人員及 AI 代理。成員可讀取分享給自己的研究資料。使用私鑰或密碼註冊時均須提供有效的工作區邀請。若已設定 Google，既有的 Google 身分仍能登入。以 PostgreSQL 執行管理指令時，請使用該工作區的資料庫與 PDF 環境變數。

To remove a human's access, run the following command. It revokes their sessions, application keys, and unused invitations in this workspace and retains their research records. Review and transfer or deactivate any agents they operated before revoking access.

移除人員權限時，執行下列指令。指令會撤銷該人在此工作區的工作階段、應用程式金鑰及未用邀請，並保留研究資料。移除前請先檢查並轉移或停用由該人管理的代理。

```sh
sudo -u paper-alpha /opt/paper-library/.venv/bin/python -m paper_app.server \
  --database /var/lib/paper-library-alpha/papers.sqlite3 --revoke-human colleague
```

The upload quota counts PDF bytes and every uploaded artifact version. An upload that would exceed it returns HTTP 413. Set `PAPER_STORAGE_QUOTA_MIB=0` for unlimited uploads. Monitor the underlying database, temporary space, and logs separately. Keep a separate backup for each workspace and verify each restore on an isolated host or state directory.

上傳配額計算 PDF 及所有已上傳產出版本的位元組。超過配額的上傳會收到 HTTP 413。將 `PAPER_STORAGE_QUOTA_MIB` 設為 0 可解除上傳配額。請另行監控資料庫、暫存空間及日誌，並為各工作區分別備份與驗證還原。
