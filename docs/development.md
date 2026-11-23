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

Run the same checks as CI with Python, Poppler, and Node.js. CI uses Node.js 22.

使用 Python、Poppler 與 Node.js 即可執行與 CI 相同的檢查。CI 使用 Node.js 22。

```sh
bash scripts/check.sh
```

For PostgreSQL, install the `postgres` extra and set `PAPER_TEST_POSTGRES_URL` to a test server where the role can create and drop temporary databases. Run `bash scripts/check.sh --postgres`. Use `pg_dump` and `pg_restore` to include the restore test.

若要測試 PostgreSQL，請安裝 `postgres` 選用依賴，並將 `PAPER_TEST_POSTGRES_URL` 指向測試伺服器，使用可建立與刪除暫存資料庫的角色，再執行 `bash scripts/check.sh --postgres`。備有 `pg_dump` 與 `pg_restore` 即可一併執行還原測試。

To measure catalog startup, run `python3 -m scripts.benchmark_snapshots --papers 10000 --comments-per-paper 1 --catalog`.

若要測量論文目錄的載入效能，請執行 `python3 -m scripts.benchmark_snapshots --papers 10000 --comments-per-paper 1 --catalog`。

## Maintain the guides · 維護指南

Keep the root README focused on setup and navigation. Update the relevant guide in `docs/` when a workflow changes, keep English and Traditional Chinese together, and verify command examples and relative links.

根目錄的 README 專注於快速安裝與文件導覽。流程變更時，請更新 `docs/` 中對應的指南，同步維護英文與繁體中文，並檢查範例指令及相對連結。
