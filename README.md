# Local paper library

Requires Python 3.11 or newer and Poppler's `pdftotext`.

```sh
python3 paper_server.py --database papers.sqlite3
```

Open <http://127.0.0.1:8765/> to compare metrics. Use the **Papers** page to import one or more PDFs, manage groups and comments, or look up publication metadata on Crossref. Select a paper name in a comparison table to open its details.

For command-line extraction, pass `--database`, `--output`, or both.

```sh
python3 extract_paper_locally.py ./cc-papers/*.pdf --database papers.sqlite3 --output new-metrics.csv
python3 paper_server.py --database papers.sqlite3 --import-csv existing-metrics.csv
```

Open `view_paper_metrics.html` directly to browse an exported CSV without the server. Metrics are extracted by text rules and may include a cited baseline or miss measurements shown only in a figure. Check the source before ranking papers.

The server binds to loopback. PDFs and SQLite data stay on the computer. A Crossref lookup sends only the DOI or title used for the search. Keep the database and its sibling `papers.sqlite3.pdfs/` directory together when backing up the library.
