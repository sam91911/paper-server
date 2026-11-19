# Local paper library

Requires Python 3.11 or newer and Poppler's `pdftotext`.

```sh
./run_paper_server.sh /path/to/papers.sqlite3
```

Open [the paper library](http://127.0.0.1:8765/papers) to import PDFs, manage groups and comments, and search Crossref. Open [Compare metrics](http://127.0.0.1:8765/) to compare extracted values and export CSVs. Press Ctrl+C to stop the server.

For related paper search, enter the main topic and any related keyword groups, one per line. A title matches when it contains every word in any one group. The results include publisher DOI links and a DOI text download. Crossref receives only the supplied title keywords or bibliographic lookup values.

To load an existing metrics CSV, run this from the repository root.

```sh
python3 -m paper_app.server --database /path/to/papers.sqlite3 --import-csv /path/to/metrics.csv
```

Keep the SQLite file and its sibling `.pdfs/` directory together when backing up the library. Extracted metrics can include values from cited baselines and can miss values shown only in figures. Check the source before ranking papers.

## Source layout

- `run_paper_server.sh` starts the loopback server.
- `paper_app/server.py` handles HTTP routes, uploads, and CSV exports.
- `paper_app/library.py` manages SQLite data and CSV imports.
- `paper_app/pdf.py` extracts metrics and stores imported PDFs.
- `paper_app/crossref.py` handles DOI lookup and title search.
- `paper_app/web/` contains the HTML, CSS, and browser scripts.
