# Storage and recovery · 儲存與還原

[Project home · 專案首頁](../README.md)

## SQLite

Run these commands from the repository root. Backup and restore verify managed PDFs and uploaded artifacts. Back up external file references separately and keep backups private. Stop the server before checking integrity so the report reflects a stable library.

從儲存庫根目錄執行以下指令。備份與還原會驗證受管理的 PDF 及上傳的產出檔。外部參照檔案需另外備份，並妥善保管備份。執行完整性檢查前請先停止伺服器，讓報告反映一致的資料庫狀態。

```sh
./run_paper_server.sh ./papers.sqlite3 --import-csv /path/to/metrics.csv
python3 -m paper_app.integrity ./papers.sqlite3
python3 -m paper_app.backup create ./papers.sqlite3 ./backup
python3 -m paper_app.backup restore ./backup ./restored.sqlite3
```

## PostgreSQL

Create a dedicated PostgreSQL 16 UTF-8 database owned by the app's database role. The app installs `citext` and applies schema migrations at startup. Artifacts live in the database, and managed PDFs live in `PAPER_PDF_DIR`. In this mode, omit the SQLite path from launcher commands.

建立專用的 PostgreSQL 16 UTF-8 資料庫，並將應用程式的資料庫角色設為擁有者。應用程式啟動時會安裝 `citext` 並更新資料表結構。產出檔存於資料庫，受管理的 PDF 則存於 `PAPER_PDF_DIR`。使用此模式時，啟動指令可省略 SQLite 路徑。

```sh
python3 -m pip install '.[postgres]'
export PAPER_DATABASE_URL='postgresql://paper@localhost/paper_library'
export PAPER_PDF_DIR='/absolute/path/to/paper-library-pdfs'
./run_paper_server.sh
```

To migrate, stop the SQLite server and point the environment variables at a new empty database and a new PDF directory. Run the following before starting PostgreSQL mode. The original SQLite library stays available for rollback. Writes after cutover stay in PostgreSQL.

若要移轉，先停止 SQLite 伺服器，再將環境變數指向全新的空資料庫與 PDF 目錄。在以 PostgreSQL 模式啟動前執行以下指令。原 SQLite 資料庫可用於回復，切換後新增的資料會留在 PostgreSQL。

```sh
python3 -m paper_app.migrate --from-sqlite ./papers.sqlite3
python3 -m paper_app.integrity
```

For a PostgreSQL backup, stop all writers, run the integrity check, then save the database dump and PDF directory together. Back up external references separately.

備份 PostgreSQL 時，先停止所有寫入程序並檢查完整性，再一併保存資料庫傾印檔和 PDF 目錄。外部參照檔案需另外備份。

```sh
python3 -m paper_app.integrity
umask 077
backup_dir=$(mktemp -d)
pg_dump --format=custom --no-owner --dbname="$PAPER_DATABASE_URL" --file="$backup_dir/library.dump"
if [ -d "$PAPER_PDF_DIR" ]; then cp -a -- "$PAPER_PDF_DIR" "$backup_dir/pdfs"; fi
```

To restore, set `PAPER_DATABASE_URL` to a new empty database and run `pg_restore --exit-on-error --single-transaction --no-owner --dbname="$PAPER_DATABASE_URL" "$backup_dir/library.dump"`. Restore the PDFs to the original absolute `PAPER_PDF_DIR` path on the restore host, then run the integrity check and open a PDF and artifact in the restored library.

還原時，將 `PAPER_DATABASE_URL` 指向全新的空資料庫，再執行 `pg_restore --exit-on-error --single-transaction --no-owner --dbname="$PAPER_DATABASE_URL" "$backup_dir/library.dump"`。在還原主機上將 PDF 放回原本的 `PAPER_PDF_DIR` 絕對路徑，接著檢查完整性，並在還原後的論文庫中開啟 PDF 與產出檔確認。
