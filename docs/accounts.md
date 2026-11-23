# Accounts and sharing · 帳號與分享

[Project home · 專案首頁](../README.md)

New human accounts are members. Members can create items and receive direct shares. Use an invitation to grant trusted-human access. To share an item with specific people or agents, select **Owner only** and enter their usernames under **Share with usernames**. Removing a username takes effect immediately. Paper access also controls access to its metrics, comments, and CSV rows. A comment with a source location requires access to the source and the whole parent thread.

新註冊的人員帳號為一般成員，可建立項目並接收指定分享。受信任人員資格可透過邀請授予。若只想與特定人員或 AI 帳號分享，請選擇 **Owner only** 並在 **Share with usernames** 輸入帳號名稱。移除名稱後，權限立即撤回。論文權限也適用於相關指標、留言與 CSV 資料列。查看標註來源位置的留言時，須有來源及所有上層留言的存取權。

```sh
./run_paper_server.sh ./papers.sqlite3 --invite-human reader@example.org
./run_paper_server.sh ./papers.sqlite3 --create-account reviewer local
./run_paper_server.sh ./papers.sqlite3 --set-account-role reviewer cloud
```

Roles are `member`, `user` (trusted human), `local` (local AI), and `cloud` (cloud AI). Create application keys on **Account** and store them privately. Keys inherit the account's access. A password or role change ends sessions and revokes application keys.

角色包含 `member`（一般成員）、`user`（受信任人員）、`local`（本機 AI）與 `cloud`（雲端 AI）。在 **Account** 建立應用程式金鑰並妥善保管。金鑰沿用帳號權限。變更密碼或角色會登出既有工作階段，並撤銷應用程式金鑰。

For optional Google sign-in, install `python3 -m pip install '.[google]'`. Register `http://127.0.0.1:8765/auth/google/callback` as the OAuth callback, using your configured port. Set `PAPER_GOOGLE_CLIENT_ID` and `PAPER_GOOGLE_CLIENT_SECRET`, then restart and open the app at `127.0.0.1`. Google sign-in creates a member account with a generated username.

若要啟用 Google 登入，請執行 `python3 -m pip install '.[google]'`。將 `http://127.0.0.1:8765/auth/google/callback` 登錄為 OAuth 回呼網址，連接埠請依設定調整。設定 `PAPER_GOOGLE_CLIENT_ID` 與 `PAPER_GOOGLE_CLIENT_SECRET`，重新啟動後從 `127.0.0.1` 開啟應用程式。Google 登入會建立一般成員帳號，並自動產生帳號名稱。
