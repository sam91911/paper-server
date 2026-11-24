# Development · 開發

[Project home · 專案首頁](../README.md)

| Path | Purpose | 用途 |
| --- | --- | --- |
| `paper_app/server.py`, `paper_app/*_routes.py` | CLI and HTTP routes | 命令列入口與 HTTP 路由 |
| `paper_app/library.py`, `paper_app/database.py`, `paper_app/sql/` | Storage and schema migrations | 資料存取與資料表移轉 |
| `paper_app/accounts.py`, `paper_app/sharing.py` | Identity and access rules | 身分驗證與存取權限 |
| `paper_app/findings.py`, `paper_app/goals.py`, `paper_app/experiments.py` | Research workflow | 研究流程 |
| `paper_app/web/`, `vscode-extension/`, `paper_client/` | Browser, editor, and AI clients | 瀏覽器、編輯器與 AI 用戶端 |
| `tests/`, `scripts/` | Tests, sample library, and benchmark | 測試、範例資料庫與效能測試 |

Run the same checks as CI with Python, Poppler, and Node.js 22. CI tests SQLite with Python 3.11 and 3.13 and runs a separate PostgreSQL 16 job.

使用 Python、Poppler 與 Node.js 22 即可執行與 CI 相同的檢查。CI 以 Python 3.11 和 3.13 測試 SQLite，另行測試 PostgreSQL 16。

```sh
bash scripts/check.sh
```

For PostgreSQL, install the `postgres` extra and set `PAPER_TEST_POSTGRES_URL` to a test server where the role can create and drop temporary databases. Run `bash scripts/check.sh --postgres`. Use `pg_dump` and `pg_restore` to include the restore test.

若要測試 PostgreSQL，請安裝 `postgres` 選用依賴，並將 `PAPER_TEST_POSTGRES_URL` 指向測試伺服器，使用可建立與刪除暫存資料庫的角色，再執行 `bash scripts/check.sh --postgres`。備有 `pg_dump` 與 `pg_restore` 即可一併執行還原測試。

Run the package check with the command below. It installs the server wheel and the client downloaded from that server in separate temporary environments. It checks enrollment, required skills, PDF intake, Git and result uploads, and human acceptance of a goal using a synthetic benchmark.

以下指令會在分開的暫存環境安裝伺服器及下載的代理用戶端。測試以合成資料驗證註冊、讀取必要技能、匯入 PDF、上傳 Git 快照與結果，以及人員驗收目標。

```sh
bash scripts/check-install.sh
```

To measure catalog startup, run `python3 -m scripts.benchmark_snapshots --papers 10000 --comments-per-paper 1 --catalog`.

若要測量論文目錄的載入效能，請執行 `python3 -m scripts.benchmark_snapshots --papers 10000 --comments-per-paper 1 --catalog`。

## Maintain the guides · 維護指南

Keep the root README focused on setup and navigation. Update the relevant guide in `docs/` when a workflow changes, keep English and Traditional Chinese together, and verify command examples and relative links.

根目錄的 README 專注於快速安裝與文件導覽。流程變更時，請更新 `docs/` 中對應的指南，同步維護英文與繁體中文，並檢查範例指令及相對連結。

## Releases · 發行版本

Set the same `0.x.y` version in the server and client `pyproject.toml` files. Push a matching `v0.x.y` tag for the release commit. After all CI jobs pass, GitHub Actions publishes the tested server wheel, client ZIP, and SHA-256 checksums.

在伺服器與用戶端的 `pyproject.toml` 設定相同的 `0.x.y` 版本，並推送發行提交所對應的 `v0.x.y` 標籤。CI 全數通過後，GitHub Actions 會發布測試過的伺服器 wheel、用戶端 ZIP 及 SHA-256 校驗檔。
