# Public deployment with Nginx · 使用 Nginx 公開部署

[Project home · 專案首頁](../README.md)

To host independent labs, use [isolated workspaces](workspaces.md) with a separate service, hostname, and database for each lab.

若要代管多個獨立實驗室，請使用[隔離工作區](workspaces.md)，為各實驗室配置獨立服務、主機名及資料庫。

Run Paper Library and Nginx on the same machine. Nginx listens on the public address and terminates HTTPS. The Python server listens on `127.0.0.1` and recognizes the configured public origin. Point your DNS record to the server and obtain a certificate for that hostname. A public IP can also be used when the certificate is valid for that IP.

在同一台機器執行論文庫及 Nginx。Nginx 在公開位址提供 HTTPS。Python 伺服器只監聽 `127.0.0.1`，並接受設定的公開來源。請設定 DNS 紀錄並為網域取得憑證。若憑證涵蓋公開 IP，也可直接使用該 IP。

From the repository, launch the app under your service account. Use an absolute database path for a managed service. For PostgreSQL, set `PAPER_DATABASE_URL` and `PAPER_PDF_DIR` and omit the SQLite path.

在儲存庫中以服務帳號啟動應用程式。使用服務管理工具時，請指定資料庫的絕對路徑。若使用 PostgreSQL，請設定 `PAPER_DATABASE_URL` 和 `PAPER_PDF_DIR`，並省略 SQLite 路徑。

```sh
python3 -m pip install .
./run_paper_server.sh /var/lib/paper-library/library.sqlite3 --port 8765 \
  --public-url https://papers.example.org
```

You can set `PAPER_PUBLIC_URL` in the service environment instead of `--public-url`. Use the full HTTPS origin, including any non-default port. Serve the app at the domain root. Keep port `8765` private and expose Nginx ports `80` and `443`.

也可在服務環境中設定 `PAPER_PUBLIC_URL`。請使用完整的 HTTPS 來源，包含非預設連接埠，並將應用程式部署於網域根路徑。保持 `8765` 為私有連接埠，對外開放 Nginx 的 `80` 和 `443`。

Copy the [Nginx configuration](../deploy/nginx-paper-library.conf) into a file loaded from Nginx's `http` context, such as `/etc/nginx/conf.d/paper-library.conf`. Replace the hostname and certificate paths and match the upstream port to the app's `--port`. The proxy preserves the request Host, supports 100 MiB uploads, rate-limits authentication endpoints, and redacts AI invitation paths from its access log. [Nginx proxy documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)

將 [Nginx 設定](../deploy/nginx-paper-library.conf) 複製到 Nginx 的 `http` 區塊載入的檔案，例如 `/etc/nginx/conf.d/paper-library.conf`。替換網域、憑證路徑及上游連接埠。設定會保留 Host 標頭、支援 100 MiB 上傳、限制驗證請求速率，並在存取日誌中遮蔽 AI 邀請路徑。

```sh
sudo nginx -t
sudo systemctl reload nginx
curl -fsS https://papers.example.org/api/openapi.json
```

Open the public URL to create or sign in to a human account with a private key. AI invitations issued by the server include its public HTTPS URL. If you use optional Google sign-in, register `https://papers.example.org/auth/google/callback` with Google.

從公開網址開啟論文庫即可使用私鑰建立人員帳號或登入。伺服器產生的 AI 邀請會使用公開 HTTPS 網址。若啟用 Google 登入，請在 Google 註冊 `https://papers.example.org/auth/google/callback`。

## Plan a public IPv4 and IPv6 rollout · 規劃公開 IPv4 與 IPv6 部署

1. Choose a host with a routable public IPv4 address and a global IPv6 address. Use one hostname and configure its DNS `A` record for IPv4 and its `AAAA` record for IPv6. The supplied Nginx configuration listens on both address families and forwards both to the same loopback service. Keep the app, database, and backup ports private. [Nginx listen documentation](https://nginx.org/en/docs/http/ngx_http_core_module.html#listen)
2. Install a publicly trusted HTTPS certificate and enable automated renewal. Use the same hostname in Nginx, `PAPER_PUBLIC_URL`, and any OAuth callback. Test from a network outside the host. Publish the `AAAA` record when IPv6 routing, the firewall, and certificate validation work end to end. [Let's Encrypt IPv6 validation](https://letsencrypt.org/docs/ipv6-support/)
3. Pilot with one member and one enrolled agent. Verify sign-in, invitations, PDF access, one artifact upload, and a database restore. A reachable server allows visitors to create member accounts. Papers, documents, goals, and artifacts still follow their sharing rules. Before advertising open signups, decide how to handle abusive accounts, upload capacity, and support. If you want anonymous reading, define a separate opt-in public catalog containing only records intended for publication.

```sh
curl -4 -fsS https://papers.example.org/api/health
curl -6 -fsS https://papers.example.org/api/health
```

An IP-only deployment can use `https://192.0.2.10` or `https://[2001:db8::10]` as its configured origin. Replace the documentation addresses with your real address and use a certificate that covers that IP. Let's Encrypt offers IP certificates with shorter lifetimes, so automatic renewal is important. A hostname gives visitors on both networks one URL and lets you change addresses without changing existing links. [Let's Encrypt IP certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)

請選擇具有公開 IPv4 及全域 IPv6 的主機，以同一網域的 `A` 與 `AAAA` 紀錄指向兩種位址。Nginx 會將兩者導向同一個只在本機監聽的服務。設定可信任的 HTTPS 憑證及自動更新後，從外部網路分別以 `curl -4` 和 `curl -6` 測試。先邀請少量使用者及代理驗證註冊、上傳及備份還原，再對外公告。研究項目仍依各自設定的權限分享。若要提供匿名瀏覽，可另行規劃僅包含明確選擇發布項目的公開目錄。

## Run under systemd · 使用 systemd 執行

The [sample systemd unit](../deploy/paper-library.service) runs the Python server on port 8765 behind Nginx. Create the `paper-library` system user and group, and install the project into `/opt/paper-library/.venv`, or adjust the unit to your paths. Put `PAPER_PUBLIC_URL=https://papers.example.org` in `/etc/paper-library.env` and restrict access to that file if it holds database or OAuth credentials. The default unit uses SQLite under `/var/lib/paper-library`. For PostgreSQL, remove the `--database` argument and configure `PAPER_DATABASE_URL` and `PAPER_PDF_DIR` in the environment file.

[systemd 範例](../deploy/paper-library.service) 讓 Python 伺服器在 Nginx 後方使用 8765 連接埠。建立 `paper-library` 系統使用者及群組，安裝至 `/opt/paper-library/.venv`，或修改單元內的路徑。請在 `/etc/paper-library.env` 設定 `PAPER_PUBLIC_URL`，如含資料庫或 OAuth 憑證則限制檔案權限。使用 PostgreSQL 時移除 `--database` 參數，並在環境檔設定 `PAPER_DATABASE_URL` 和 `PAPER_PDF_DIR`。

```sh
sudo install -m 0644 deploy/paper-library.service /etc/systemd/system/paper-library.service
sudo systemctl daemon-reload
sudo systemctl enable --now paper-library.service
curl -fsS https://papers.example.org/api/health
```

`GET /api/health` returns HTTP 200 when the app can read its configured database and HTTP 503 otherwise. It requires no credential. To check from outside the server, set the GitHub Actions repository variable `PAPER_LIBRARY_PUBLIC_URL` to your public HTTPS origin and run **Paper Library availability** once. GitHub then schedules the same check twice an hour. Failed checks appear in the workflow history and can notify users according to their GitHub Actions notification settings.

`GET /api/health` 在可讀取設定的資料庫時回傳 HTTP 200，失敗時回傳 HTTP 503，無須憑證。若要從伺服器外部檢查，請將 GitHub Actions 儲存庫變數 `PAPER_LIBRARY_PUBLIC_URL` 設為公開 HTTPS 來源，並手動執行一次 **Paper Library availability**。GitHub 之後每小時排程檢查兩次。失敗會記錄於工作流程歷史，並依使用者的 GitHub Actions 通知設定發送通知。

To offer Git over SSH, run the [Git-only OpenSSH listener](git-ssh.md#enable-the-git-only-ssh-listener--啟用-git-專用-ssh-服務) alongside the web service.

若要透過 SSH 提供 Git 存取，請在網頁服務之外啟用 [Git 專用 OpenSSH 監聽服務](git-ssh.md#enable-the-git-only-ssh-listener--啟用-git-專用-ssh-服務)。

## Upgrade while serving traffic · 不中斷服務升級

Use the supplied reloadable unit and make `/opt/paper-library` a symlink to a release directory containing its own `.venv`. If you already run an older unit or use a real directory at that path, switch to this layout and start the updated unit once during a maintenance window. Keep database and PDF paths outside the release directory.

Install the management command from a trusted checkout, then pass a published release tag to install and activate the wheel tested by CI. The command downloads the wheel and its SHA-256 manifest from the project's GitHub Releases and verifies the wheel before installation. Replace `v0.x.y` with the release you intend to deploy.

```sh
sudo install -m 0755 scripts/paper-libraryctl.sh /usr/local/bin/paper-libraryctl
sudo paper-libraryctl upgrade-release v0.x.y
sudo paper-libraryctl status
sudo paper-libraryctl logs -f
```

The command creates a separate virtual environment, atomically switches the release link, and waits for systemd's journal to report that the replacement worker is ready. The `status` command shows the configured tag. If activation fails, the upgrade restores the previous link and prints recent logs. For installations using optional dependencies, run `sudo PAPER_LIBRARY_EXTRAS=postgres,google paper-libraryctl upgrade-release v0.x.y` with the extras that apply. Use `sudo paper-libraryctl upgrade .` to install from a source checkout.

Use `paper-libraryctl releases` to find an earlier release, then `sudo paper-libraryctl rollback /opt/paper-library-releases/RELEASE` to activate it if it can start against the current schema. PostgreSQL releases reject migrations newer than they recognize, so a rollback across those migrations requires a compatible build or a coordinated database restore. Keep the previous release until the journal reports that its worker has drained. Use `upgrade --restart` or `rollback --restart` to restart the service during a maintenance window.

Use live upgrades for releases whose database schema works with both worker versions during the handoff. Schedule maintenance for incompatible schema changes, supervisor changes, and changes to the unit or its environment. The package CI job rehearses an SQLite upgrade from the previous tagged source, installs the candidate wheel, and checks that existing metadata, comments, and PDF permissions survive. For local development, start with `./run_paper_server.sh ./papers.sqlite3 --reloadable` and send `SIGHUP` to that process.

將 `/opt/paper-library` 設為指向版本目錄的符號連結，每個版本使用獨立的 `.venv`。若原本使用舊版服務單元或實體目錄，請在維護時段切換並啟動更新後的單元一次。升級時先安裝新版本，再原子切換連結並執行 `systemctl reload paper-library.service`。監督程序會保留監聽連接埠，待新程序完成資料庫初始化後，讓舊程序處理完進行中的請求。請在日誌確認新的 `HTTP worker … ready` 訊息。若啟動失敗，舊程序會繼續服務。資料庫結構必須同時支援兩個版本，才能使用不中斷升級。

## Enable request timing logs · 啟用請求計時日誌

Set `PAPER_REQUEST_METRICS=1` in the service environment and restart Paper Library. Read the `request_metric` JSON records with `journalctl -u paper-library`. Each record includes the method, route group, HTTP status, elapsed milliseconds in the app handler, and whether the handler returned with a status. Known file routes replace record IDs with `{id}`, while other routes are grouped as `other`. The timing records omit query strings, authorization headers, and request bodies. Use Nginx timing separately for traffic through the public proxy.

在服務環境中設定 `PAPER_REQUEST_METRICS=1` 並重新啟動論文庫。使用 `journalctl -u paper-library` 查看 `request_metric` JSON 記錄。每筆包含請求方法、路由群組、HTTP 狀態碼、應用程式處理時間（毫秒），以及處理程式是否帶有狀態碼返回。已知檔案路由以 `{id}` 取代資料識別碼，其餘路由歸入 `other`。計時記錄省略查詢字串、授權標頭及請求內容。透過公開反向代理的流量另用 Nginx 取得計時。

## Verify a backup by restoring it · 以還原驗證備份

Use a separate restore directory or host with no production traffic. For SQLite, run the following as a user that can read the library and write the backup directory. The restore command checks database integrity, stored PDFs, and uploaded research artifacts.

請使用沒有正式流量的獨立還原目錄或主機。SQLite 請以能讀取論文庫並寫入備份目錄的使用者執行下列指令。還原指令會驗證資料庫、PDF 及上傳的研究產出檔。

```sh
verification_dir=$(mktemp -d)
python3 -m paper_app.backup create /var/lib/paper-library/library.sqlite3 "$verification_dir/backup"
python3 -m paper_app.backup restore "$verification_dir/backup" "$verification_dir/restored.sqlite3"
python3 -m paper_app.integrity "$verification_dir/restored.sqlite3"
./run_paper_server.sh "$verification_dir/restored.sqlite3" --port 18765
```

In the restored library, sign in with a valid account, open a known PDF and a stored research artifact, and compare a recent goal and its progress with the backup cutoff. For PostgreSQL, stop writers for the coordinated dump and file copy, restore on a separate host with the original absolute PDF paths, and run the same checks. External references and privately held identity files need their own backups. [PostgreSQL backup and restore commands](storage.md#postgresql)

在還原後的論文庫登入，開啟已知 PDF 及上傳產出檔，並核對一個近期目標與進度。PostgreSQL 備份時先停止寫入，在獨立主機按原絕對路徑還原 PDF，再執行相同檢查。外部參照檔及使用者私下持有的身分檔案須另行備份。 [PostgreSQL 備份及還原指令](storage.md#postgresql)
