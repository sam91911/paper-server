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

## Benchmark concurrent research activity · 測量並行研究活動

Run a browsing baseline, then repeat with agents. Both commands run the real HTTP handlers on loopback using a fresh synthetic library. PostgreSQL mode uses `PAPER_TEST_POSTGRES_URL` to create and remove a temporary database. Omit `--postgres` to use temporary SQLite instead.

先測量純瀏覽的基準，再加入代理重測。兩個指令都使用全新的合成資料庫，在本機迴路介面執行實際的 HTTP 處理程式。PostgreSQL 模式依據 `PAPER_TEST_POSTGRES_URL` 建立並清除暫存資料庫。省略 `--postgres` 則使用暫存 SQLite。

```sh
python3 -m scripts.benchmark_workflow --postgres --users 4 --agents 0 --rounds 30
python3 -m scripts.benchmark_workflow --postgres --users 4 --agents 8 --rounds 30
```

Each browsing round opens the catalog, a paper and its PDF, an experiment, the ZIP listing, and a source file preview. Each agent checks goals and sends a heartbeat every round, with an upload on the first round and then every `--upload-every` rounds. Keep `--papers`, `--archive-files`, `--upload-kib`, and `--pause-ms` the same to compare runs. The report shows client-observed p50, p95, and maximum latency in milliseconds, total throughput, and failures. The command exits nonzero on any failed request.

每一輪瀏覽會開啟論文目錄、論文與 PDF、實驗、ZIP 檔案清單及原始碼預覽。代理每輪查詢目標並送出心跳，第一輪上傳一次，之後每隔 `--upload-every` 輪再上傳。比較測試時請固定 `--papers`、`--archive-files`、`--upload-kib` 與 `--pause-ms`。報告提供用戶端觀察到的 p50、p95 與最長延遲（毫秒）、總吞吐量及失敗數。任何請求失敗時，指令會以非零狀態結束。

Use `--request-metrics` to include server-side timing logs in a benchmark. The benchmark measures local HTTP and database work with repeated access to the same PDF and archive. Agent rounds intentionally compress time and may begin together. Setup, Nginx, TLS, remote networks, and the background metadata worker are outside the timed workload.

測試時加入 `--request-metrics` 可輸出伺服器端計時日誌。測試會重複讀取同一份 PDF 與封存檔，以測量本機 HTTP 與資料庫工作。代理輪次刻意縮短，也可能同時開始。計時範圍不包含初始化、Nginx、TLS、遠端網路或背景書目更新。

Compare p95 and maximum latency for each operation. Use throughput to compare repeated runs with the same request mix. Adding agents changes the mix and total request count. If a small number of requests are much slower than p95, use the timing logs and repeat the test before drawing conclusions. For deployed performance, measure through the public HTTPS endpoint as well.

請依操作比較 p95 與最長延遲，並在相同請求組合下比較吞吐量。增加代理會改變請求組合及總數。如果少數請求明顯慢於 p95，請查看計時日誌並重測，再判斷原因。評估正式環境時，也請透過公開 HTTPS 網址量測。

## Maintain the guides · 維護指南

Keep the root README focused on setup and navigation. Update the relevant guide in `docs/` when a workflow changes, keep English and Traditional Chinese together, and verify command examples and relative links.

根目錄的 README 專注於快速安裝與文件導覽。流程變更時，請更新 `docs/` 中對應的指南，同步維護英文與繁體中文，並檢查範例指令及相對連結。

## Releases · 發行版本

Set the same `0.x.y` version in the server and client `pyproject.toml` files. Push a matching `v0.x.y` tag for the release commit. After all CI jobs pass, GitHub Actions publishes the tested server wheel, client ZIP, and SHA-256 checksums.

在伺服器與用戶端的 `pyproject.toml` 設定相同的 `0.x.y` 版本，並推送發行提交所對應的 `v0.x.y` 標籤。CI 全數通過後，GitHub Actions 會發布測試過的伺服器 wheel、用戶端 ZIP 及 SHA-256 校驗檔。

## Agent prompts

The browser's enrollment and check-in templates live in `paper_app/web/prompts/`. Edit `registration.md` for enrollment, `agent-check.md` for the shared check-in workflow, and `options.json` for rotation, schedule, and research-mode wording. Keep the named `{{placeholders}}` used to insert account details and commands at runtime.

The default API skill is `paper_app/web/prompts/default-skill.md`. Edit `paper_client/review-prompt.md` to change the review instructions shared by the local and cloud workstation clients.
