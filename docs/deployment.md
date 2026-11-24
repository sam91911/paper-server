# Public deployment with Nginx · 使用 Nginx 公開部署

[Project home · 專案首頁](../README.md)

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
