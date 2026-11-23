# Local paper library

## Project goal

Build a research server that helps researchers answer two questions: **What matters now? What should we do next?** Bring literature, discussion, design, and experimentation into one workflow so researchers can move quickly from a promising idea to evidence about whether it is achievable.

- **Identify what matters.** Synthesize papers and documents to surface open questions, conflicting results, and gaps in the evidence. Use threaded comments and references to brainstorm directions and explain why a question is worth pursuing now.
- **Test feasibility early.** Define what success would look like and choose the smallest experiment that could inform the next decision. Use AI to help design a prototype or experiment, carry it out, and analyze the results under explicit conditions.
- **Decide what to do next.** Compare results with published baselines and earlier runs. Link conclusions to source passages, methods, and outputs so researchers can judge the evidence and decide whether to refine the goal, complete the design and run a larger experiment, or pursue another direction.

### Research data management

The server must apply the CIA triad to papers, documents, discussions, and experiment records throughout the research workflow.

- **Confidentiality.** Limit access to authorized researchers and AI agents. Respect sharing decisions and revocations when reading, citing, exporting, or sending research material to an AI provider.
- **Integrity.** Track who contributed or changed a record and which source or artifact version supports each finding. Detect unexpected changes to stored files and flag citations that need review.
- **Availability.** Keep research records accessible to authorized collaborators and recoverable after failures. Back up the database and managed files together, and verify that a restore recovers both the records and their evidence links.

## Getting started

Requires Python 3.11 or newer and Poppler's `pdftotext`. Citing PDF pages also uses Poppler's `pdfinfo`.

```sh
./run_paper_server.sh /path/to/papers.sqlite3
```

Use the bottom bar to switch between [Compare](http://127.0.0.1:8765/), [Papers](http://127.0.0.1:8765/papers), [Documents](http://127.0.0.1:8765/documents), [Experiments](http://127.0.0.1:8765/experiments), and [Account](http://127.0.0.1:8765/account). Press Ctrl+C to stop the server.

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

The **server** (`paper_app`) stores research data, enforces access rules, and serves the web UI and HTTP API. The **workstation client** (`paper_client`) fetches authorized context over that API, runs the model or calls the configured provider, and can post a comment. It can be installed on a separate computer using `python3 -m pip install ./paper_client` from a copy of this repository. For a source-only setup, copy the `paper_client` directory and run Python from its parent directory.

Use **Review with AI** on a paper, a document, or a comment thread to get a terminal command for Windows PowerShell, macOS, or Linux. The browser reports tools installed on the server host. Run **Copy local tool check** on the workstation to check its tools without signing in. When the server is on another computer, forward its library port to a loopback port on the workstation and pass that port with `--port`.

For local review, install `llama-completion` from llama.cpp and use a local GGUF model. PDF review also requires Poppler's `pdftotext`. Create a key as a **Local AI** account, then provide it when prompted. You can use `--username reviewer` to sign in with a password instead.

```sh
python3 -m paper_client --check
python3 -m paper_client 1 --page 2 --model /path/to/model.gguf
python3 -m paper_client --document 2 --model /path/to/model.gguf --post
python3 -m paper_client --thread 3 --model /path/to/model.gguf --post
```

For cloud review, use a **Cloud AI** account and select `--cloud` instead of `--model`. Set `PAPER_AI_CLOUD_URL` to your provider's HTTPS Chat Completions URL and `PAPER_AI_CLOUD_MODEL` to its model ID. The command prompts before sending the permitted context and prompts separately for the provider key. On Windows, run `py -3` instead of `python3`. [Chat Completions request format](https://developers.openai.com/api/reference/resources/chat)

Commands preview the result unless you add `--post`. Posted comments default to owner-only. Thread reviews are always posted owner-only because the model may have read replies with different audiences. The agent can read only what its own account can access. Generated replies to a document appear in that document's discussion.

The original `python3 -m paper_app.local_ai` command still works with a full installation.

## VS Code extension

Install the VSIX with **Extensions: Install from VSIX**, then run **Paper Library: Configure Server and Key** in the Command Palette. Enter an origin such as `http://127.0.0.1:8765` and a key from the library's **Account** page. Use **Open Document**, **New Document**, or **Post Comment** under **Paper Library**. Save Markdown with the usual VS Code save command. See the [extension source and setup](vscode-extension/README.md).

To load an existing metrics CSV, run this from the repository root.

```sh
python3 -m paper_app.server --database /path/to/papers.sqlite3 --import-csv /path/to/metrics.csv
```

Keep the SQLite file and its sibling `.pdfs/` directory together when backing up the library. Extracted metrics can include values from cited baselines and can miss values shown only in figures. Check the source before ranking papers.

## Research workflow

1. Create a Markdown document for literature notes and add **Research findings** backed by PDF pages, Markdown line ranges, or uploaded artifact versions. Check published baselines against the source page.
2. Open **What to do next** to propose a goal with a reason to pursue it now, a specific uncertainty, and supporting findings. Researchers and AI agents can propose and discuss goals. The human workspace owner sets priorities and selects goals for testing. Priority 1 is highest, and ties follow proposal order.
3. Draft a feasibility brief for a selected goal. Specify the approach, baseline finding, success criterion, measurement conditions, and budget. The workspace owner confirms the brief to create a linked experiment. Use **Copy brief** to hand the Markdown to your external tools. The confirmed brief and baseline revision stay linked to each run.
4. Run the experiment externally. Record the methods, settings, and status in **Experiments**, then upload the output and cite the exact version from a run finding. Numeric findings use a metric, decimal value, unit, and measurement conditions.
5. Return to the goal to record a decision. The server compares numeric results when the metric, unit, and conditions match. A failed run, incompatible measurement, or changed baseline is inconclusive. The workspace owner records the rationale and chooses another iteration, promotion to a full design brief, or setting the goal aside. The full design draft carries forward the earlier evidence and can be revised before confirmation.

Goal records and linked experiments follow current workspace and evidence access. The original per-run and artifact permissions still apply. Explicit experiment editor grants let collaborators record runs. Use **Discuss goal** or the finding’s **Discuss** action to start a scoped thread. If an edited Markdown source flags a citation for review, check the current line range and update the citation revision.

### Synthetic pilot

Create a separate library and start the server. The generator prints the test username and password, a local AI application key, the workspace path, and the finding IDs.

```sh
pilot_dir=$(mktemp -d)
python3 -m scripts.research_pilot --goals "$pilot_dir/pilot.sqlite3"
./run_paper_server.sh "$pilot_dir/pilot.sqlite3"
```

Sign in with the printed human credentials and open the printed workspace path on `http://127.0.0.1:8765`. From the conclusion, open the mock methods PDF and inspect the two CSV run outputs. In **Compare findings**, compare the published 80% baseline with the 90% full benchmark result for a 10 percentage-point difference. Compare the same baseline with the 100% clean-scan result to see the conditions mismatch. Look for the agent’s qualitative O/0 observation and the human discussion attached to the conclusion.

Open the printed goal workflow path to see the two AI proposals ranked by the researcher. The clean-only run has an inconclusive decision. The comparable ten-scan run met the criterion and opened a draft full design brief. Run the generator without `--goals` to start with the findings alone and walk through the goal workflow manually.

To participate as the local AI account, send its printed application key as `Authorization: Bearer <key>`. Set `PILOT_KEY` to the key before running these examples. The fresh pilot creates document `1`, baseline `1`, full-run finding `2`, and initial discussion comment `1`.

```sh
curl -H "Authorization: Bearer $PILOT_KEY" \
  'http://127.0.0.1:8765/api/research-findings?document_id=1'
curl -H "Authorization: Bearer $PILOT_KEY" \
  'http://127.0.0.1:8765/api/research-findings?document_id=1&left=1&right=2'
curl -H "Authorization: Bearer $PILOT_KEY" -H 'Content-Type: application/json' \
  -d '{"document_id":1,"parent_id":1,"body":"Test scans containing both O and 0.","audience":"local"}' \
  'http://127.0.0.1:8765/api/comments'
```

`POST /api/research-findings` accepts `document_id`, `statement`, `kind` (`observation`, `baseline`, or `run_result`), and an `evidence` array. Use `{"kind":"pdf","id":1,"page":1}` for a PDF, `{"kind":"document","id":1,"start":2,"end":2,"revision":1}` for Markdown, and `{"kind":"run_artifact","id":1}` for an uploaded run artifact version. Send `metric`, `value` as a decimal string, `unit`, and `conditions` together for numeric findings. For baselines, include a PDF citation and `"verified_baseline":true` after checking the source. To edit a finding you authored, include its `id` and current `revision`. To start a thread, send the finding’s ID as `finding_id` with the new document comment.

### Goal API

Read visible goals, supporting findings, and copyable brief Markdown with `GET /api/research-goals?document_id=1`. An external agent can read the findings and submit a proposal using its own application key.

```sh
curl -H "Authorization: Bearer $PILOT_KEY" \
  'http://127.0.0.1:8765/api/research-goals?document_id=1'
curl -H "Authorization: Bearer $PILOT_KEY" -H 'Content-Type: application/json' \
  -d '{"document_id":1,"action":"propose","question":"Do O and 0 errors warrant a dedicated check?","rationale":"The full run found one such error.","uncertainty":"How frequent is the error across samples?","evidence_ids":[4]}' \
  'http://127.0.0.1:8765/api/research-goals'
```

Send an `action` and `document_id` with every goal write. After proposal, include the `goal_id`. Start a goal thread with `goal_id` on a new document comment, then reply using its `parent_id`.

| Action | Additional fields |
| --- | --- |
| `propose` | `question`, `rationale`, `uncertainty`, `evidence_ids` (supporting finding IDs) |
| `draft` | `approach`, `baseline_id` (finding ID), `criterion`, `conditions`, `budget` |
| `rank` | `revision`, `priority`, `selected` (boolean) |
| `confirm` | `revision`, `brief_id` |
| `decide` | `revision`, `brief_id`, `run_id`, `result_id` (finding ID), `outcome` (`met`, `missed`, or `inconclusive`), `next_step` (`iterate`, `design`, or `set_aside`), `rationale` |
| `revise_design` | `revision`, `brief_id`, and the same brief fields as `draft` |

The `revision` is the current goal revision. Rank, confirm, decide, and design revision require the human workspace owner. Authors can update source locations in findings that a goal or brief already cites. Use a follow-up finding when the evidence targets change.

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
- `paper_client/` contains the standalone review client and workstation tool checks.
- `paper_app/backup.py` and `paper_app/integrity.py` back up, restore, and check local data.

## Backup and restore

Create a backup in a new directory, then restore it to a new database path:

```sh
python3 -m paper_app.backup create /path/to/papers.sqlite3 /path/to/backup
python3 -m paper_app.backup restore /path/to/backup /path/to/restored.sqlite3
```

The command holds a SQLite write lock while copying the database and verified PDF files, so imports and other writes wait until the backup finishes. It verifies SHA-256 hashes for managed PDFs and uploaded artifact versions when creating and restoring a backup. The SQLite snapshot includes research goals, briefs, decisions, and uploaded artifacts. Keep the backup private because it contains account credentials and library content. Test the restored library before relying on a backup. Back up externally referenced files separately.

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

`GET /api/paper-page` offers the same cursor pattern for accessible, unarchived papers, in pages of up to 100. The browser paper picker uses `GET /api/paper-catalog` for numbered pages and filters. It accepts `q`, `group`, `publisher`, `from_year`, `through_year`, and `page`, plus `facets=1` to include the account and filter options. The browser fetches paper metadata on selection and loads location choices and archived papers when their sections are opened. Document text and discussions are fetched when their items are selected, and discussions load up to 50 root threads at a time.

Run `python3 -m scripts.benchmark_snapshots --papers 10000 --comments-per-paper 1 --catalog` to compare the browser's startup JSON request counts, response sizes and database read times with and without a preselected paper.
