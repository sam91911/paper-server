#!/usr/bin/env python3
"""Serve the paper library on localhost or import an existing metrics CSV."""

import argparse
import csv
import getpass
import hashlib
import io
import json
import platform
import re
import shutil
import sqlite3
import subprocess
from threading import Event, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import accounts, crossref, google_signin, library, metadata_sync, sharing
from .pdf import import_pdf, spreadsheet_text

WEB_ROOT = Path(__file__).resolve().with_name("web")
PAGE = ("index.html", "text/html; charset=utf-8")
ASSETS = {
    "/": PAGE,
    "/papers": PAGE,
    "/account": PAGE,
    "/documents": PAGE,
    "/assets/library.js": ("library.js", "text/javascript; charset=utf-8"),
    "/assets/metrics.js": ("metrics.js", "text/javascript; charset=utf-8"),
    "/assets/style.css": ("style.css", "text/css; charset=utf-8"),
}
MAX_PDF_BYTES = 50 * 1024 * 1024


def lookup_stored_paper(paper):
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
    def send_data(self, status, data, content_type="application/json; charset=utf-8", *, filename=None, pdf_download=None, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        if pdf_download:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(pdf_download, safe='')}")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if content_type == "application/pdf":
            policy = "frame-ancestors 'self'"
        else:
            policy = ("default-src 'none'; script-src 'self'; style-src 'self'; "
                      "connect-src 'self'; frame-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data, *, cookie=None):
        self.send_data(status, json.dumps(data).encode("utf-8"), cookie=cookie)

    def session_token(self):
        return accounts.read_token(self.headers.get("Cookie"))

    def current_account(self, db):
        authorization = self.headers.get("Authorization")
        if authorization is None:
            return accounts.current_account(db, self.session_token())
        match = re.fullmatch(r"Bearer (pl_[A-Za-z0-9_-]{43})", authorization, re.I)
        return accounts.current_account(db, match[1], application_key=True) if match else None

    def require_browser_account(self, db):
        if self.headers.get("Authorization") is not None:
            raise accounts.SignInRequired
        return self.require_account(db)

    def require_account(self, db):
        account = self.current_account(db)
        if account is None:
            raise accounts.SignInRequired
        return account

    def require_human(self, db):
        account = self.require_account(db)
        if account["role"] != "user":
            raise sharing.AccessDenied
        return account

    def update_session(self, data):
        if self.headers.get("Authorization") is not None:
            raise accounts.SignInRequired
        token = self.session_token()
        with library.connect(self.server.database) as db:
            db.execute("BEGIN IMMEDIATE")
            if self.path == "/api/sign-out":
                accounts.sign_out(db, token)
                account, token = None, ""
            elif self.path == "/api/change-password":
                accounts.change_password(db, self.require_account(db), data.get("current_password"),
                                         data.get("new_password"))
                account, token = None, ""
            else:
                if self.path == "/api/register":
                    accounts.register_human(db, data)
                account, token = accounts.sign_in(
                    db, data.get("username"), data.get("password"),
                    old_token=token,
                )
        max_age = accounts.SESSION_SECONDS if token else 0
        cookie = f"{accounts.COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"
        self.send_json(200, {"account": account}, cookie=cookie)

    def origin_allowed(self):
        valid = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        return host in valid and origin in (None, f"http://{host}")

    def log_request(self, code="-", size="-"):
        if urlsplit(self.path).path == "/auth/google/callback":
            self.log_message('"%s /auth/google/callback" %s %s', self.command, str(code), str(size))
        else:
            super().log_request(code, size)

    def google_available(self):
        return self.server.google_config is not None and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def redirect(self, target, cookie=None):
        self.send_response(303)
        self.send_header("Location", target)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def google_login(self, url):
        if not self.google_available():
            self.send_json(404, {"error": "Google sign-in is unavailable."})
            return
        config = self.server.google_config
        if url.path == "/auth/google":
            with library.connect(self.server.database) as db:
                redirect, state = google_signin.begin(db, config)
            self.redirect(redirect, f"{google_signin.COOKIE}={state}; Path=/auth/google; "
                          f"HttpOnly; SameSite=Lax; Max-Age={google_signin.TTL}")
            return
        try:
            params = parse_qs(url.query)
            code, = params["code"]
            state, = params["state"]
            with library.connect(self.server.database) as db:
                flow = google_signin.consume(db, self.headers.get("Cookie"), state)
            claims = google_signin.verify(config, code, flow)
            with library.connect(self.server.database) as db:
                db.execute("BEGIN IMMEDIATE")
                account_id = google_signin.account(db, claims)
                token = accounts.start_session(db, account_id, self.session_token())
        except (KeyError, ValueError, OSError, sqlite3.Error):
            self.redirect("/account?google=failed")
        else:
            self.redirect("/account", f"{accounts.COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; "
                          f"Max-Age={accounts.SESSION_SECONDS}")

    def do_GET(self):
        if not self.origin_allowed():
            self.send_json(403, {"error": "Local origin required"})
            return
        url = urlsplit(self.path)
        route = url.path
        if route in ("/auth/google", "/auth/google/callback"):
            self.google_login(url)
        elif route in ASSETS:
            filename, content_type = ASSETS[route]
            self.send_data(200, (WEB_ROOT / filename).read_bytes(), content_type)
        elif match := re.fullmatch(r"/papers/([1-9][0-9]{0,18})/source\.pdf", route):
            self.serve_pdf(int(match[1]), download=url.query == "download=1")
        elif route == "/exports/metrics.csv":
            self.export_metrics()
        elif route in ("/api/usernames", "/api/agent-options", "/api/document"):
            try:
                with library.connect(self.server.database) as db:
                    account = self.require_account(db)
                    if route == "/api/document":
                        value = parse_qs(url.query).get("id", [""])[0]
                        if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) >= 2**63:
                            raise LookupError
                        document = sharing.document_for(db, account, int(value))
                        if document is None:
                            raise LookupError
                        data = {"document": dict(document)}
                    elif route == "/api/usernames":
                        query = parse_qs(url.query).get("q", [""])[0]
                        data = accounts.suggest_usernames(db, query)
                    else:
                        data = {"server_os": platform.system(), "pdf_text": bool(shutil.which("pdftotext")),
                                "llama": bool(shutil.which("llama-completion"))}
                self.send_json(200, data)
            except accounts.SignInRequired:
                self.send_json(401, {"error": "Sign in to continue."})
            except LookupError:
                self.send_json(404, {"error": "This document is unavailable."})
            except sqlite3.Error:
                self.send_json(500, {"error": "Could not read the library database"})
        elif route in ("/api/library", "/api/compare", "/api/paper-details", "/api/account", "/api/documents"):
            try:
                with library.connect(self.server.database) as db:
                    db.execute("BEGIN")
                    account = self.current_account(db)
                    if route == "/api/account":
                        data = {"account": account, "google_available": self.google_available()}
                        if account and self.headers.get("Authorization") is None:
                            data["keys"] = accounts.list_keys(db, account["id"])
                    elif route == "/api/documents":
                        data = library.snapshot(db, view="documents", account=account)
                    else:
                        data = library.snapshot(db, view=route.rsplit("/", 1)[-1], account=account)
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
                db.execute("BEGIN")
                account = self.current_account(db)
                for row in library.metric_rows(db, account):
                    writer.writerow(
                        row[field] if field in ("page", "value") else spreadsheet_text(row[field])
                        for field in library.FIELDS
                    )
        except sqlite3.Error:
            self.send_json(500, {"error": "Could not export the metrics database"})
            return
        self.send_data(200, output.getvalue().encode("utf-8-sig"),
                       "text/csv; charset=utf-8", filename="paper-metrics.csv")

    def serve_pdf(self, paper_id, *, download=False):
        try:
            with library.connect(self.server.database) as db:
                db.execute("BEGIN")
                paper = sharing.paper_for(db, paper_id, self.current_account(db))
            if not paper["sha256"]:
                self.send_json(404, {"error": "No verified PDF for this paper. Import the PDF first."})
                return
            with Path(paper["path"]).open("rb") as source:
                payload = source.read(MAX_PDF_BYTES + 1)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            self.send_json(404, {"error": "The local PDF is unavailable. Re-import it to restore access."})
            return
        except (OverflowError, sharing.AccessDenied):
            self.send_json(404, {"error": "Paper not found or unavailable"})
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
            self.send_data(200, payload, "application/pdf",
                           pdf_download=Path(paper["path"]).name if download else None)

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
            if not 0 < size <= 1_300_000:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if self.path in ("/api/register", "/api/sign-in", "/api/sign-out", "/api/change-password"):
                self.update_session(data)
                return
            if self.path == "/api/lookup":
                if "paper_id" in data:
                    paper_id = data["paper_id"]
                    if type(paper_id) is not int:
                        raise ValueError("Select a paper")
                    with library.connect(self.server.database) as db:
                        db.execute("BEGIN")
                        account = self.current_account(db)
                        if account is None or account["role"] != "user":
                            raise sharing.AccessDenied
                        paper = sharing.paper_for(db, paper_id, account, owner_only=True)
                    matches = lookup_stored_paper(paper)
                else:
                    matches = crossref.lookup(data.get("kind"), data.get("query"))
                self.send_json(200, matches)
                return
            if self.path == "/api/search-papers":
                matches = crossref.search_papers(
                    data.get("topic"), data.get("keywords", []), data.get("publisher", ""),
                    data.get("year_from"), data.get("year_to"),
                )
                self.send_json(200, matches)
                return
            with library.connect(self.server.database) as db:
                db.execute("BEGIN IMMEDIATE")
                result = self.update(db, data)
            self.send_json(200, {"ok": True, **(result or {})})
        except accounts.SignInRequired:
            self.send_json(401, {"error": "Sign in to continue."})
        except sharing.EditConflict as error:
            self.send_json(409, {"error": str(error)})
        except sharing.AccessDenied:
            self.send_json(403, {"error": "This item is unavailable or requires owner access."})
        except accounts.CommentAccessDenied:
            self.send_json(403, {"error": "Only the account that posted this comment can change it."})
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
            with library.connect(self.server.database) as db:
                account = self.require_account(db)
            audience = sharing.validate_audience(self.headers.get("X-Paper-Audience", "owner"))
            recipients_header = self.headers.get("X-Paper-Recipients")
            recipients = json.loads(unquote(recipients_header)) if recipients_header is not None else None
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
            result = import_pdf(self.server.database, filename, payload, account, audience, recipients)
            self.send_json(200, result)
        except accounts.SignInRequired:
            self.send_json(401, {"error": "Sign in to upload PDFs."})
        except sharing.AccessDenied:
            self.send_json(403, {"error": "This PDF could not be imported by this account."})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except subprocess.SubprocessError:
            self.send_json(422, {"error": "Could not extract this PDF. Check that it opens and is unlocked."})
        except FileNotFoundError:
            self.send_json(500, {"error": "The server could not open a local file or run pdftotext"})
        except (sqlite3.Error, OSError):
            self.send_json(500, {"error": "Could not save the local PDF import"})

    def update(self, db, data):
        if self.path in ("/api/application-keys", "/api/revoke-key"):
            account = self.require_browser_account(db)
            if self.path == "/api/application-keys":
                return {"key": accounts.create_key(db, account["id"], data.get("label"))}
            accounts.revoke_key(db, account["id"], data.get("key_id"))
            return
        if self.path == "/api/groups":
            self.require_human(db)
            library.create_group(db, data.get("name"))
            return
        if self.path == "/api/documents":
            document_id = sharing.save_document(db, self.require_account(db), data)
            revision = db.execute("SELECT revision FROM documents WHERE id=?", (document_id,)).fetchone()["revision"]
            return {"document_id": document_id, "revision": revision}
        if self.path in ("/api/comments", "/api/delete-comment"):
            return self.update_comment(db, data)
        if self.path not in ("/api/paper-access", "/api/metadata", "/api/memberships", "/api/archive-paper"):
            raise LookupError
        paper_id = data.get("paper_id")
        if type(paper_id) is not int:
            raise ValueError("Select a paper")
        if self.path == "/api/paper-access":
            sharing.set_paper_audience(db, paper_id, self.require_account(db), data.get("audience"),
                                       data.get("recipients"))
            if "allow_title" in data:
                if type(data["allow_title"]) is not bool:
                    raise ValueError("Choose whether to allow a title lookup.")
                metadata_sync.set_title_lookup(db, paper_id, data["allow_title"])
            return
        account = self.current_account(db)
        sharing.paper_for(db, paper_id, account, owner_only=self.path in (
            "/api/metadata", "/api/archive-paper", "/api/memberships",
        ))
        if self.path == "/api/metadata":
            library.save_metadata(db, paper_id, data)
            db.execute("UPDATE paper_metadata_checks SET next_check=0 WHERE paper_id=?", (paper_id,))
        elif self.path == "/api/archive-paper":
            archived = data.get("archived")
            if type(archived) is not bool:
                raise ValueError("Choose whether to archive or restore the paper")
            library.set_archived(db, paper_id, archived)
        else:
            self.require_human(db)
            library.set_memberships(db, paper_id, data.get("groups"))

    def update_comment(self, db, data):
        account = self.require_account(db)
        paper_id, document_id = data.get("paper_id"), data.get("document_id")
        if type(paper_id) is int and document_id is None:
            sharing.paper_for(db, paper_id, account)
        elif type(document_id) is int and paper_id is None:
            if sharing.document_for(db, account, document_id) is None:
                raise sharing.AccessDenied
        else:
            raise ValueError("Select a paper or document.")
        comment_id = data.get("comment_id")
        if comment_id is not None and type(comment_id) is not int:
            raise ValueError("Select a comment")
        if self.path == "/api/delete-comment":
            if comment_id is None:
                raise ValueError("Select a comment")
            library.delete_comment(db, paper_id, comment_id, account["id"], document_id)
            return
        comment_id = library.save_comment(
            db, paper_id, data.get("body"), account, comment_id, kind=data.get("kind", "user"),
            parent_id=data.get("parent_id"), doi_refs=data.get("doi_refs"),
            audience=data.get("audience"), location=data.get("location"),
            recipients=data.get("recipients"), document_id=document_id,
        )
        return {"comment_id": comment_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("papers.sqlite3"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--import-csv", type=Path, help="Import a metrics CSV and exit")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--invite-human", metavar="EMAIL", help="Issue a one-time browser signup code")
    modes.add_argument("--create-account", nargs=2, metavar=("USERNAME", "ROLE"))
    modes.add_argument("--set-account-role", nargs=2, metavar=("USERNAME", "ROLE"))
    args = parser.parse_args()
    try:
        library.initialize(args.database)
        if args.invite_human:
            with library.connect(args.database) as db:
                token = accounts.create_invite(db, args.invite_human)
            print(f"Invitation for {args.invite_human} (valid for 24 hours): {token}")
            return
        if args.create_account or args.set_account_role:
            username, role = args.create_account or args.set_account_role
            with library.connect(args.database) as db:
                if args.create_account:
                    password = getpass.getpass("Password: ")
                    if password != getpass.getpass("Confirm password: "):
                        raise ValueError("Passwords do not match.")
                    accounts.create_account(db, username, password, role)
                else:
                    accounts.set_role(db, username, role)
            print(f"Saved account {username} ({role}).")
            return
        if args.import_csv:
            with args.import_csv.open(encoding="utf-8-sig", newline="") as stream:
                with library.connect(args.database) as db:
                    count = library.import_csv(db, stream, args.import_csv.absolute().parent)
            print(f"Imported metrics for {count} paper path(s).")
            return
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.database = args.database.absolute()
            server.google_config = google_signin.configuration(server.server_port)
            stop = Event()
            worker = Thread(target=metadata_sync.run, args=(server.database, stop), daemon=True)
            worker.start()
            print(f"Paper library at http://127.0.0.1:{server.server_port}/", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                stop.set()
    except (sqlite3.Error, csv.Error, ValueError, OSError, EOFError) as error:
        parser.exit(1, f"Paper library: {error}\n")


if __name__ == "__main__":
    main()
