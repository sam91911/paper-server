#!/usr/bin/env python3
"""Serve the paper library on localhost or import an existing metrics CSV."""

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import crossref, library
from .pdf import import_pdf, spreadsheet_text

WEB_ROOT = Path(__file__).resolve().with_name("web")
PAGE = ("index.html", "text/html; charset=utf-8")
ASSETS = {
    "/": PAGE,
    "/papers": PAGE,
    "/assets/library.js": ("library.js", "text/javascript; charset=utf-8"),
    "/assets/metrics.js": ("metrics.js", "text/javascript; charset=utf-8"),
    "/assets/style.css": ("style.css", "text/css; charset=utf-8"),
}
MAX_PDF_BYTES = 50 * 1024 * 1024


def lookup_stored_paper(database, paper_id):
    if type(paper_id) is not int:
        raise ValueError("Select a paper")
    with library.connect(database) as db:
        paper = db.execute("SELECT doi,title,path FROM papers WHERE id=?", (paper_id,)).fetchone()
    if paper is None:
        raise ValueError("Paper not found")

    title = paper["title"].strip() or Path(paper["path"]).stem.replace("_", " ").strip()
    if paper["doi"].strip():
        try:
            matches = crossref.lookup("doi", paper["doi"])
        except ValueError:
            matches = []
        if matches:
            return matches
    return crossref.lookup("title", title[:500])


class Handler(BaseHTTPRequestHandler):
    def send_data(self, status, data, content_type="application/json; charset=utf-8", *, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; "
                         "style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data):
        self.send_data(status, json.dumps(data).encode("utf-8"))

    def origin_allowed(self):
        valid = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        return host in valid and origin in (None, f"http://{host}")

    def do_GET(self):
        if not self.origin_allowed():
            self.send_json(403, {"error": "Local origin required"})
            return
        route = urlsplit(self.path).path
        if route in ASSETS:
            filename, content_type = ASSETS[route]
            self.send_data(200, (WEB_ROOT / filename).read_bytes(), content_type)
        elif match := re.fullmatch(r"/papers/([1-9][0-9]{0,18})/source\.pdf", route):
            self.serve_pdf(int(match[1]))
        elif route == "/exports/metrics.csv":
            self.export_metrics()
        elif route in ("/api/library", "/api/compare", "/api/paper-details"):
            try:
                with library.connect(self.server.database) as db:
                    db.execute("BEGIN")
                    data = library.snapshot(db, view=route.rsplit("/", 1)[-1])
                self.send_json(200, data)
            except sqlite3.Error:
                self.send_json(500, {"error": "Could not read the library database"})
        else:
            self.send_json(404, {"error": "Unknown route"})

    def export_metrics(self):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(library.FIELDS)
        try:
            with library.connect(self.server.database) as db:
                for row in library.metric_rows(db):
                    writer.writerow(
                        row[field] if field in ("page", "value") else spreadsheet_text(row[field])
                        for field in library.FIELDS
                    )
        except sqlite3.Error:
            self.send_json(500, {"error": "Could not export the metrics database"})
            return
        self.send_data(200, output.getvalue().encode("utf-8-sig"),
                       "text/csv; charset=utf-8", filename="paper-metrics.csv")

    def serve_pdf(self, paper_id):
        try:
            with library.connect(self.server.database) as db:
                paper = db.execute(
                    "SELECT path, sha256 FROM papers WHERE id=?", (paper_id,)
                ).fetchone()
            if paper is None or not paper["sha256"]:
                self.send_json(404, {"error": "No verified PDF for this paper. Import the PDF first."})
                return
            with Path(paper["path"]).open("rb") as source:
                payload = source.read(MAX_PDF_BYTES + 1)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            self.send_json(404, {"error": "The local PDF is unavailable. Re-import it to restore access."})
            return
        except OverflowError:
            self.send_json(404, {"error": "Paper not found"})
            return
        except (sqlite3.Error, OSError):
            self.send_json(500, {"error": "Could not read the local PDF"})
            return

        if len(payload) > MAX_PDF_BYTES:
            self.send_json(413, {"error": "The PDF is larger than the 50 MiB viewer limit"})
        elif (b"%PDF-" not in payload[:1024] or
              hashlib.sha256(payload).hexdigest() != paper["sha256"]):
            self.send_json(409, {"error": "The local file no longer matches this paper record."})
        else:
            self.send_data(200, payload, "application/pdf")

    def do_POST(self):
        if not self.origin_allowed():
            self.send_json(403, {"error": "Local origin required"})
            return
        if self.path == "/api/papers":
            self.upload_pdf()
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "Use application/json"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 128_000:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if self.path == "/api/lookup":
                matches = (lookup_stored_paper(self.server.database, data["paper_id"])
                           if "paper_id" in data else
                           crossref.lookup(data.get("kind"), data.get("query")))
                self.send_json(200, matches)
                return
            if self.path == "/api/search-papers":
                self.send_json(200, crossref.search_papers(data.get("topic"), data.get("keywords", [])))
                return
            with library.connect(self.server.database) as db:
                self.update(db, data)
            self.send_json(200, {"ok": True})
        except (ValueError, KeyError, OverflowError) as error:
            self.send_json(400, {"error": str(error)})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "A group already exists or a selected record is missing"})
        except sqlite3.Error:
            self.send_json(500, {"error": "Could not update the library database"})
        except RuntimeError as error:
            self.send_json(502, {"error": str(error)})
        except LookupError:
            self.send_json(404, {"error": "Unknown route"})

    def upload_pdf(self):
        if self.headers.get_content_type() != "application/pdf":
            self.send_json(415, {"error": "Choose a PDF file"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            filename = unquote(self.headers.get("X-Paper-Filename", ""), errors="strict")
            filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
            if not filename.lower().endswith(".pdf") or any(ord(char) < 32 for char in filename):
                raise ValueError("Choose a file with a .pdf extension")
            if len(filename.encode("utf-8")) > 240:
                filename = filename.encode("utf-8")[:236].decode("utf-8", "ignore") + ".pdf"
            if not 0 < size <= MAX_PDF_BYTES:
                raise ValueError("Choose a PDF of up to 50 MiB")
            self.connection.settimeout(60)
            payload = self.rfile.read(size)
            if len(payload) != size or b"%PDF-" not in payload[:1024]:
                raise ValueError("The upload is incomplete or is not a PDF")
            result = import_pdf(self.server.database, filename, payload)
            self.send_json(200, result)
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except subprocess.SubprocessError:
            self.send_json(422, {"error": "Could not extract this PDF. Check that it opens and is unlocked."})
        except FileNotFoundError:
            self.send_json(500, {"error": "The server could not open a local file or run pdftotext"})
        except (sqlite3.Error, OSError):
            self.send_json(500, {"error": "Could not save the local PDF import"})

    def update(self, db, data):
        if self.path == "/api/groups":
            library.create_group(db, data.get("name"))
            return
        if self.path not in ("/api/metadata", "/api/comments", "/api/memberships"):
            raise LookupError
        paper_id = data.get("paper_id")
        if type(paper_id) is not int:
            raise ValueError("Select a paper")
        if self.path == "/api/metadata":
            library.save_metadata(db, paper_id, data)
        elif self.path == "/api/comments":
            comment_id = data.get("comment_id")
            if comment_id is not None and type(comment_id) is not int:
                raise ValueError("Select a comment")
            library.save_comment(db, paper_id, data.get("body"), comment_id)
        else:
            library.set_memberships(db, paper_id, data.get("groups"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("papers.sqlite3"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--import-csv", type=Path, help="Import a metrics CSV and exit")
    args = parser.parse_args()
    try:
        library.initialize(args.database)
        if args.import_csv:
            with args.import_csv.open(encoding="utf-8-sig", newline="") as stream:
                with library.connect(args.database) as db:
                    count = library.import_csv(db, stream, args.import_csv.absolute().parent)
            print(f"Imported metrics for {count} paper path(s).")
            return
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.database = args.database.absolute()
            print(f"Paper library at http://127.0.0.1:{server.server_port}/", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except (sqlite3.Error, csv.Error, ValueError, OSError) as error:
        parser.exit(1, f"Paper library: {error}\n")


if __name__ == "__main__":
    main()
