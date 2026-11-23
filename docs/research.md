# Research workflow · 研究流程

[Project home · 專案首頁](../README.md)

| Step | What to do | 操作方式 |
| --- | --- | --- |
| 1 | Write literature notes under **Documents**. Cite PDF pages, Markdown lines, or exact artifact versions in **Research findings**. | 在 **Documents** 撰寫文獻筆記，並在 **Research findings** 引用 PDF 頁碼、Markdown 行範圍或確切的產出版本。 |
| 2 | Under **What to do next**, propose a question, explain why it matters, and link supporting findings. The human workspace owner ranks and selects goals. | 在 **What to do next** 提出問題、說明理由，並連結支持證據。由人員工作區擁有者排序並選擇目標。 |
| 3 | Draft a feasibility brief with a baseline, success criterion, conditions, and budget. Confirm it to create a linked experiment. | 撰寫可行性測試計畫，列出基準、成功標準、測試條件及預算。確認後即可建立關聯實驗。 |
| 4 | Run the experiment externally. In **Experiments**, record methods and results, upload outputs, and cite the exact version in a run finding. | 在外部執行實驗，再於 **Experiments** 記錄方法與結果、上傳產出，並在實驗發現中引用具體版本。 |
| 5 | Compare results with the baseline. Numeric comparisons require matching metrics, units, and conditions. Record whether to iterate, draft a full design, or set the goal aside. | 將結果與基準比較。數值比較須使用相同指標、單位與條件。記錄要再試一次、撰寫完整設計，或擱置目標。 |

Use **Papers** to search Crossref by topic, publisher, or year. The background lookup can fill blank metadata using a DOI. Owners can opt in to sending a title or filename for lookup. PDF bytes are processed locally.

在 **Papers** 可依主題、出版者或年份搜尋 Crossref。背景查詢可利用 DOI 補齊空白的書目欄位。擁有者可選擇允許送出標題或檔名查詢。PDF 檔案內容在本機處理。

## Detect and correct metrics · 偵測與更正指標

Enter comma-separated keywords when uploading a PDF. To scan a stored PDF, select **Papers → Metric corrections → Detect metrics from PDF**. Detection looks for measurements near literal phrases, ignores case, and keeps the default detection rules when the field is empty. Keywords can also label measurements such as `PSNR 32 dB`. A new scan keeps previous corrections and removals.

上傳 PDF 時可輸入以逗號分隔的關鍵字。若要掃描已儲存的 PDF，請選擇 **Papers → Metric corrections → Detect metrics from PDF**。系統會尋找關鍵字附近的數值，不區分大小寫，欄位留空時沿用預設規則。關鍵字也可用來標示 `PSNR 32 dB` 等測量值。重新掃描會保留已更正及已移除的指標。

In **Papers → Metric corrections**, select a metric, check its source, and save the revised fields with a reason. Compare and CSV exports use the latest correction. The original extraction and each edit remain in the history.

在 **Papers → Metric corrections** 選取指標，核對來源後，填寫更正資料與理由並儲存。**Compare** 與 CSV 匯出使用最新更正值。原始擷取值和每次更正都保留在紀錄中。

For a false positive, enter a reason and select **Remove metric**. The row disappears from Compare, CSV exports, and the active list. Open **Removed metrics** to inspect it or restore it.

若指標是誤判結果，填寫理由後選擇 **Remove metric**。該筆資料會從 **Compare**、CSV 匯出和有效指標清單移除。可在 **Removed metrics** 查看或恢復該筆資料。

Paper owners can grant or revoke edit access for an individual metric by username. Human and AI editors also need read access to the paper. Trusted humans can correct legacy unowned metrics and use **Take ownership** to manage their sharing.

論文擁有者可依帳號授予或撤銷單一指標的編輯權。人員與 AI 編輯者也都需要論文的讀取權限。受信任人員可以更正舊資料中未分配擁有者的指標，也可選擇 **Take ownership** 來管理分享。

AI clients can list metrics at `GET /api/paper-metrics?paper_id=<id>` and edit them with `POST /api/paper-metrics`. For removal or restoration, send `action: "remove"` or `action: "restore"` along with the metric ID, current revision, and reason. Add `removed=1` to the list query to find removed metrics. Fetch history at `GET /api/metric-history?metric_id=<id>`.

AI 用戶端可使用 `GET /api/paper-metrics?paper_id=<id>` 查詢指標，再用 `POST /api/paper-metrics` 編輯。移除或恢復時，請提供 `action: "remove"` 或 `action: "restore"`、指標 ID、目前版本與理由。查詢時加上 `removed=1` 可列出已移除的指標。使用 `GET /api/metric-history?metric_id=<id>` 查看歷史紀錄。

## Try a sample project · 試用範例專案

The pilot creates a separate library with sample evidence, goals, and experiment runs. Sign in with the printed credentials and open the printed workspace path. Compare the 80% baseline with the 90% full run. The 100% clean-only run uses different conditions and yields an inconclusive comparison.

此範例會建立獨立的資料庫，內含證據、研究目標與實驗紀錄。使用指令輸出的帳密登入，再開啟輸出中的工作區路徑。比較 80% 的基準值與 90% 的完整測試結果。僅使用清晰掃描的測試雖達 100%，但條件不同，無法根據這項比較得出結論。

```sh
pilot_dir=$(mktemp -d)
python3 -m scripts.research_pilot --goals "$pilot_dir/pilot.sqlite3"
./run_paper_server.sh "$pilot_dir/pilot.sqlite3"
```
