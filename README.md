# Local paper library

Requires Python 3.11 or newer and Poppler's `pdftotext`.

```sh
./run_paper_server.sh /path/to/papers.sqlite3
```

Use the bottom bar to switch between [Compare](http://127.0.0.1:8765/), [Papers](http://127.0.0.1:8765/papers), [Documents](http://127.0.0.1:8765/documents), and [Account](http://127.0.0.1:8765/account). Press Ctrl+C to stop the server.

Anyone can select **Create a human account** on the **Account** page. New members can create their own items and read items shared with their username. An optional invitation gives access to trusted-human audiences. The operator can also change the tier later. Use `local` or `cloud` for AI accounts and `member` for access by direct sharing only.

```sh
python3 -m paper_app.server --database /path/to/papers.sqlite3 --invite-human reader@example.org
python3 -m paper_app.server --database /path/to/papers.sqlite3 --create-account reviewer local
python3 -m paper_app.server --database /path/to/papers.sqlite3 --set-account-role agent local
```

Use **Account** to sign in with your username and password or create and revoke application keys. The browser displays a new key once. API clients send it as `Authorization: Bearer <key>`. Keys inherit their account's access. A password or tier change ends sessions and revokes application keys. Email is visible only to its account.

- **PDFs, documents, and comments** support both account tiers and sharing with specific usernames. For access limited to a named list, select **Owner only** and enter those usernames in **Share with usernames**. Start typing a username or display name for suggestions. Removing a username revokes that grant. A paper's access also limits its metadata, comments, metrics, and CSV rows.
- **Documents** have a dedicated Markdown editor. The Markdown editor shows a live preview beside the source on wider screens. Insert links to DOIs and local PDFs. On Papers or in a document preview, open permitted PDFs inline or in a separate tab. Opening a linked PDF requires access to that PDF.
- **Comments** can have DOI references and replies. Add a location by choosing a PDF and page number or a Markdown document and line number. A location stores only the target and number. The server shows the entire comment only to accounts that can access the paper, the target, the comment, and every parent comment.
- **Existing data** keeps its human accounts. Previously unclassified AI accounts migrate to cloud AI until the operator reclassifies them. Unowned papers are available to human accounts. Previously shared items migrate from all accounts to human and local AI, and from AI-only to local AI only.

Crossref search groups results by publisher, then journal or conference such as JSSC or ISSCC, with the newest papers first in each venue. Related-paper searches accept a main topic, optional keyword groups, a publisher name, and an inclusive year range. The paper library also filters local records by publisher and year.

The server checks for missing bibliographic fields in the background and fills blank fields when it finds a match. It uses a stored DOI or one it can identify on the first page of a verified PDF. Under **Paper file**, owners can opt in to sending a stored title or filename to Crossref when DOI lookup is insufficient. Title-based autofill requires one exact normalized title match. PDF bytes are processed locally.

## Optional Google sign-in

Create a Google OAuth web client and register the exact callback `http://127.0.0.1:8765/auth/google/callback`. If you use another server port, register that port instead. Install `google-auth[requests]`, set `PAPER_GOOGLE_CLIENT_ID` and `PAPER_GOOGLE_CLIENT_SECRET` in the server environment, and restart it. Open the app at `127.0.0.1` to see the Google option. Keep the client secret out of the repository. [Google OpenID Connect setup](https://developers.google.com/identity/openid-connect/openid-connect)

Google verifies the account identity. The app creates a new member account with its own generated username and preserves that username on later sign-ins. Google sign-in does not link to an existing password account with the same email or grant a trusted-human tier.

## Local and cloud AI reviews

Use **Review with AI** on a paper, a document, or a comment thread to get a terminal command for Windows PowerShell, macOS, or Linux. The browser reports tools installed on the server host. Use **Copy local tool check** to check a different computer without signing in. Run the command from the project directory on the same computer as the server, or forward the library port to your computer.

For local review, install `llama-completion` from llama.cpp and use a local GGUF model. PDF review also requires Poppler's `pdftotext`. Create a key as a **Local AI** account, then provide it when prompted. You can use `--username reviewer` to sign in with a password instead.

```sh
python3 -m paper_app.local_ai 1 --page 2 --model /path/to/model.gguf
python3 -m paper_app.local_ai --document 2 --model /path/to/model.gguf --post
python3 -m paper_app.local_ai --thread 3 --model /path/to/model.gguf --post
```

For cloud review, use a **Cloud AI** account and select `--cloud` instead of `--model`. Set `PAPER_AI_CLOUD_URL` to your provider's HTTPS Chat Completions URL and `PAPER_AI_CLOUD_MODEL` to its model ID. The command prompts before sending the permitted context and prompts separately for the provider key. On Windows, run `py -3` instead of `python3`. [Chat Completions request format](https://developers.openai.com/api/reference/resources/chat)

Commands preview the result unless you add `--post`. Posted comments default to owner-only. Thread reviews are always posted owner-only because the model may have read replies with different audiences. The agent can read only what its own account can access. Generated replies to a document appear in that document's discussion.

## VS Code extension

Install the VSIX with **Extensions: Install from VSIX**, then run **Paper Library: Configure Server and Key** in the Command Palette. Enter an origin such as `http://127.0.0.1:8765` and a key from the library's **Account** page. Use **Open Document**, **New Document**, or **Post Comment** under **Paper Library**. Save Markdown with the usual VS Code save command. See the [extension source and setup](vscode-extension/README.md).

To load an existing metrics CSV, run this from the repository root.

```sh
python3 -m paper_app.server --database /path/to/papers.sqlite3 --import-csv /path/to/metrics.csv
```

Keep the SQLite file and its sibling `.pdfs/` directory together when backing up the library. Extracted metrics can include values from cited baselines and can miss values shown only in figures. Check the source before ranking papers.

## Local demo

Run `./run_paper_server.sh .paper-demo/papers.sqlite3` to open the populated example library. Use the credentials in `.paper-demo/accounts.txt`. The trusted human account can open the **Mobile vision benchmark reading notes** document and preview its local PDF links. The demo includes restricted PDFs so the local AI and cloud AI accounts see different results.

## Source layout

- `run_paper_server.sh` starts the loopback server.
- `paper_app/server.py` handles HTTP routes, uploads, and CSV exports.
- `paper_app/*_routes.py` contains account, document, comment, and paper write operations.
- `paper_app/library.py` manages SQLite data and CSV imports.
- `paper_app/pdf.py` extracts metrics and stores imported PDFs.
- `paper_app/crossref.py` handles DOI lookup and title search.
- `paper_app/metadata_sync.py` checks for missing metadata in the background.
- `paper_app/web/` contains the HTML, CSS, and browser scripts.
- `paper_app/backup.py` and `paper_app/integrity.py` back up, restore, and check local data.

## Backup and restore

Create a backup in a new directory, then restore it to a new database path:

```sh
python3 -m paper_app.backup create /path/to/papers.sqlite3 /path/to/backup
python3 -m paper_app.backup restore /path/to/backup /path/to/restored.sqlite3
```

The command holds a SQLite write lock while copying the database and verified PDF files, so imports and other writes wait until the backup finishes. It checks each stored PDF's SHA-256 when creating and restoring the backup and checks SQLite integrity on restore. Keep the backup private: it contains account credentials and library content. Test the restored library before relying on a backup. CSV-only records can refer to external files; those files are not included and must be backed up separately. External processes that modify PDF files outside the app are not coordinated by the database lock.

## Development

The core server uses the Python standard library. For the optional Google sign-in dependencies, install the project with `python3 -m pip install '.[google]'`. Install Poppler separately to provide `pdftotext`. The server warns at startup if it is missing; PDF import requires it.

Run the checks locally:

```sh
python3 -m compileall -q paper_app
python3 -m unittest discover -s tests -v
for test in tests/*.mjs; do node "$test"; done
```

The JavaScript checks require Node.js; the application itself does not. To reproduce the synthetic snapshot benchmark, run `python3 -m scripts.benchmark_snapshots`.

To check database integrity and find missing, changed, or unreferenced managed PDF files without deleting anything, stop the server first and run `python3 -m paper_app.integrity /path/to/papers.sqlite3`. The server must be stopped to avoid reporting an in-progress import as an orphan. Investigate any orphan before removing it.

API clients that do not need a complete metric snapshot can read `GET /api/metric-page`, then follow each non-null `next_after` value with `?after=<value>`. Each page contains up to 500 accessible rows. Cursors are intended for a single traversal; concurrent edits can change later pages, so use the complete snapshot or a backup when a consistent point-in-time view is required. The comparison page currently loads the full metric dataset to support global filtering, sorting and trade-off analysis, but renders its chart and source table in pages of 100 rows.

`GET /api/paper-page` offers the same cursor pattern for accessible, unarchived papers, in pages of up to 100. The browser paper picker filters the complete accessible paper list and displays 100 choices per page. Document text and paper or document discussions are fetched only when selected; discussions load up to 50 root threads at a time.
