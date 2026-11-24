#!/usr/bin/env python3
"""Serve the paper library on localhost or import an existing metrics CSV."""

import argparse
import csv
import getpass
import hashlib
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
from threading import Event, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import database as storage
from . import account_routes, accounts, ai_accounts, comment_routes, crossref, document_routes, experiment_routes, experiments, findings, goals, google_signin, library, metadata_sync, openapi, paper_routes, pdf, reviews, sharing, skills, tools_catalog
from .pdf import import_pdf, spreadsheet_text

WEB_ROOT = Path(__file__).resolve().with_name("web")
PAGE = ("index.html", "text/html; charset=utf-8")
ASSETS = {
    "/": PAGE,
    "/papers": PAGE,
    "/account": PAGE,
    "/documents": PAGE,
    "/skills": ("skills.html", "text/html; charset=utf-8"),
    "/assets/skills.js": ("skills.js", "text/javascript; charset=utf-8"),
    "/experiments": ("experiments.html", "text/html; charset=utf-8"),
    "/assets/experiments.js": ("experiments.js", "text/javascript; charset=utf-8"),
    "/assets/findings.js": ("findings.js", "text/javascript; charset=utf-8"),
    "/assets/goals.js": ("goals.js", "text/javascript; charset=utf-8"),
    "/assets/api.js": ("api.js", "text/javascript; charset=utf-8"),
    "/assets/human-keys.js": ("human-keys.js", "text/javascript; charset=utf-8"),
    "/assets/documents.js": ("documents.js", "text/javascript; charset=utf-8"),
    "/assets/boot.js": ("boot.js", "text/javascript; charset=utf-8"),
    "/assets/library.js": ("library.js", "text/javascript; charset=utf-8"),
    "/assets/metrics.js": ("metrics.js", "text/javascript; charset=utf-8"),
    "/assets/style.css": ("style.css", "text/css; charset=utf-8"),
}
MAX_PDF_BYTES = 50 * 1024 * 1024
LOG = logging.getLogger(__name__)


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


def public_url(value):
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username is not None
            or url.path not in ("", "/") or "?" in value or "#" in value
            or not re.fullmatch(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::[0-9]+)?", url.netloc)
            or url.port == 0):
        raise ValueError("Set the public URL to an HTTPS origin such as https://papers.example.org.")
    host = url.netloc.lower()
    if url.port == 443:
        host = host.rsplit(":", 1)[0]
    return f"https://{host}"


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
        match = re.fullmatch(r"(?i:Bearer) ((pl_ai_|pl_)[A-Za-z0-9_-]{43})", authorization)
        if not match:
            return None
        if match[2] == accounts.AI_SESSION_PREFIX:
            return accounts.current_account(db, match[1], ai_session=True)
        return accounts.current_account(db, match[1], application_key=True)

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

    def request_origin(self):
        host = (self.headers.get("Host") or "").lower()
        public = getattr(self.server, "public_url", None)
        if public:
            configured = urlsplit(public)
            if host == configured.netloc or (configured.port is None and host == configured.netloc + ":443"):
                return public
        if host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            return f"http://{host.removesuffix(':80')}"
        if self.server.server_port == 80 and host in {"127.0.0.1", "localhost"}:
            return f"http://{host}"
        return None

    def origin_allowed(self):
        origin = self.request_origin()
        return origin is not None and self.headers.get("Origin") in (None, origin)

    def session_cookie(self, token):
        max_age = accounts.SESSION_SECONDS if token else 0
        secure = "; Secure" if self.request_origin().startswith("https://") else ""
        return f"{accounts.COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{secure}"

    def log_request(self, code="-", size="-"):
        if self.path.startswith(ai_accounts.REGISTRATION_PREFIX):
            self.log_message('"%s %s[redacted]" %s %s', self.command, ai_accounts.REGISTRATION_PREFIX, code, size)
        elif urlsplit(self.path).path == "/auth/google/callback":
            self.log_message('"%s /auth/google/callback" %s %s', self.command, str(code), str(size))
        else:
            super().log_request(code, size)

    def google_available(self):
        config = self.server.google_config
        return config is not None and config[2] == f"{self.request_origin()}/auth/google/callback"

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
            secure = "; Secure" if self.request_origin().startswith("https://") else ""
            self.redirect(redirect, f"{google_signin.COOKIE}={state}; Path=/auth/google; "
                          f"HttpOnly; SameSite=Lax; Max-Age={google_signin.TTL}{secure}")
            return
        try:
            params = parse_qs(url.query)
            code, = params["code"]
            state, = params["state"]
            with library.connect(self.server.database) as db:
                flow = google_signin.consume(db, self.headers.get("Cookie"), state)
            claims = google_signin.verify(config, code, flow)
            with library.connect(self.server.database) as db:
                storage.begin(db, write=True)
                account_id = google_signin.account(db, claims)
                token = accounts.start_session(db, account_id, self.session_token())
        except storage.ERRORS + (KeyError, ValueError, OSError):
            self.redirect("/account?google=failed")
        else:
            self.redirect("/account", self.session_cookie(token))

    def do_GET(self):
        if not self.origin_allowed():
            self.send_json(403, {"error": "Library origin required"})
            return
        url = urlsplit(self.path)
        route = url.path
        if route in ("/auth/google", "/auth/google/callback"):
            self.google_login(url)
        elif route == "/api/openapi.json":
            self.send_json(200, openapi.document(self.server.server_port, getattr(self.server, "public_url", None)))
        elif route in ("/api/reviews", "/api/review-agents"):
            self.read_reviews(url)
        elif route == "/api/skills" or route.startswith("/api/skills/"):
            self.read_skills(url)
        elif route in ASSETS:
            filename, content_type = ASSETS[route]
            self.send_data(200, (WEB_ROOT / filename).read_bytes(), content_type)
        elif match := re.fullmatch(r"/papers/([1-9][0-9]{0,18})/source\.pdf", route):
            self.serve_pdf(int(match[1]), download=url.query == "download=1")
        elif route == "/exports/metrics.csv":
            self.export_metrics()
        elif route in ("/api/paper-catalog", "/api/paper-detail", "/api/paper-archive", "/api/paper-comment-targets",
                       "/api/paper-metrics", "/api/metric-history"):
            try:
                with library.connect(self.server.database) as db:
                    storage.begin(db)
                    data = paper_routes.read_papers(self, db, url, self.current_account(db))
                self.send_json(200, data)
            except accounts.SignInRequired:
                self.send_json(401, {"error": "Sign in to continue."})
            except sharing.AccessDenied:
                self.send_json(404, {"error": "Paper not found or unavailable."})
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
            except storage.ERRORS as error:
                LOG.error("Paper catalog read failed (%s)", type(error).__name__)
                self.send_json(500, {"error": "Could not read the paper library."})
        elif route in ("/api/metric-page", "/api/paper-page"):
            params = parse_qs(url.query)
            after = params.get("after", ["0"])[0]
            if not re.fullmatch(r"0|[1-9][0-9]{0,18}", after) or int(after) >= 2**63:
                self.send_json(400, {"error": "Invalid page cursor."})
                return
            try:
                with library.connect(self.server.database) as db:
                    storage.begin(db)
                    reader = library.metric_page if route == "/api/metric-page" else library.paper_page
                    data = reader(db, self.current_account(db), after=int(after))
                self.send_json(200, data)
            except storage.ERRORS as error:
                LOG.error("Page read failed (%s)", type(error).__name__)
                self.send_json(500, {"error": "Could not read library page."})
        elif route in ("/api/paper-comments", "/api/document-comments"):
            params = parse_qs(url.query)
            is_document = route == "/api/document-comments"
            value = params.get("document_id" if is_document else "paper_id", [""])[0]
            if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) >= 2**63:
                self.send_json(400, {"error": "Choose a document." if is_document else "Choose a paper."})
                return
            before = params.get("before", [None])[0]
            if before is not None and (not re.fullmatch(r"[1-9][0-9]{0,18}", before) or int(before) >= 2**63):
                self.send_json(400, {"error": "Invalid comment cursor."})
                return
            try:
                with library.connect(self.server.database) as db:
                    storage.begin(db)
                    account = self.current_account(db)
                    comments = library.comment_snapshot(db, account, documents=is_document,
                                                        document_id=int(value) if is_document else None,
                                                        paper_id=None if is_document else int(value),
                                                        before=int(before) if before else None, root_limit=50)
                roots = [item["id"] for item in comments if item["parent_id"] is None]
                self.send_json(200, {"comments": comments, "next_before": min(roots) if len(roots) == 50 else None})
            except storage.ERRORS as error:
                LOG.error("Comment read failed (%s)", type(error).__name__)
                self.send_json(500, {"error": "Could not read comments."})
        elif route in ("/api/experiments", "/api/experiment-detail", "/api/research-tools", "/api/research-findings", "/api/research-goals"):
            try:
                with library.connect(self.server.database) as db:
                    storage.begin(db)
                    account = self.require_account(db)
                    if route == "/api/research-tools":
                        data = {"tools": tools_catalog.list_tools(db, account), "host_tools": tools_catalog.host_tools()}
                    elif route == "/api/research-findings":
                        data = findings.read(db, account, parse_qs(url.query, keep_blank_values=True))
                    elif route == "/api/research-goals":
                        params = parse_qs(url.query, keep_blank_values=True)
                        data = goals.read(db, account, findings.query_id(params, "document_id"))
                    elif route == "/api/experiments":
                        data = {"experiments": experiments.visible_experiments(db, account)}
                    else:
                        value = parse_qs(url.query).get("id", [""])[0]
                        if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) >= 2**63:
                            raise ValueError("Choose an experiment.")
                        data = experiments.detail(db, account, int(value))
                self.send_json(200, data)
            except accounts.SignInRequired:
                self.send_json(401, {"error": "Sign in to continue."})
            except sharing.AccessDenied:
                self.send_json(404, {"error": "Research item unavailable."})
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
            except storage.ERRORS as error:
                LOG.error("Research read failed (%s)", type(error).__name__)
                self.send_json(500, {"error": "Could not read research data."})
        elif match := re.fullmatch(r"/research-versions/([1-9][0-9]{0,18})/file", route):
            try:
                with library.connect(self.server.database) as db:
                    account = self.require_account(db)
                    filename, payload = experiments.version_content(db, account, int(match[1]))
                self.send_data(200, payload, "application/octet-stream", pdf_download=filename)
            except accounts.SignInRequired:
                self.send_json(401, {"error": "Sign in to continue."})
            except (sharing.AccessDenied, LookupError, OverflowError):
                self.send_json(404, {"error": "File unavailable."})
            except storage.ERRORS + (ValueError,):
                self.send_json(500, {"error": "Could not read this file."})
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
            except storage.ERRORS as error:
                LOG.error("Database read failed (%s)", type(error).__name__)
                self.send_json(500, {"error": "Could not read the library database"})
        elif route in ("/api/library", "/api/compare", "/api/paper-details", "/api/account", "/api/documents"):
            try:
                with library.connect(self.server.database) as db:
                    storage.begin(db)
                    account = self.current_account(db)
                    if route == "/api/account":
                        data = {"account": account, "google_available": self.google_available()}
                        if account and self.headers.get("Authorization") is None:
                            data["keys"] = accounts.list_keys(db, account["id"])
                    elif route == "/api/documents":
                        data = library.snapshot(db, view="documents", account=account,
                                                include_comments=parse_qs(url.query).get("comments") != ["none"],
                                                document_summaries=parse_qs(url.query).get("content") == ["summary"])
                    else:
                        include_comments = parse_qs(url.query).get("comments") != ["none"]
                        data = library.snapshot(db, view=route.rsplit("/", 1)[-1], account=account,
                                                include_comments=include_comments)
                self.send_json(200, data)
            except storage.ERRORS as error:
                LOG.error("Database snapshot failed (%s)", type(error).__name__)
                self.send_json(500, {"error": "Could not read the library database"})
        else:
            self.send_json(404, {"error": "Unknown route"})

    def export_metrics(self):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(library.FIELDS)
        try:
            with library.connect(self.server.database) as db:
                storage.begin(db)
                account = self.current_account(db)
                for row in library.metric_rows(db, account):
                    writer.writerow(
                        row[field] if field in ("page", "value") else spreadsheet_text(row[field])
                        for field in library.FIELDS
                    )
        except storage.ERRORS as error:
            LOG.error("Metrics export failed (%s)", type(error).__name__)
            self.send_json(500, {"error": "Could not export the metrics database"})
            return
        self.send_data(200, output.getvalue().encode("utf-8-sig"),
                       "text/csv; charset=utf-8", filename="paper-metrics.csv")

    def serve_pdf(self, paper_id, *, download=False):
        try:
            with library.connect(self.server.database) as db:
                storage.begin(db)
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
        except storage.ERRORS + (OSError,) as error:
            LOG.error("PDF read failed (%s)", type(error).__name__)
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

    def read_reviews(self, url):
        try:
            params = parse_qs(url.query, keep_blank_values=True)
            with library.connect(self.server.database) as db:
                storage.begin(db)
                account = self.require_account(db)
                kind = params.get("kind", [None])[0]
                target_id = skills.query_id(params["target_id"][0]) if "target_id" in params else None
                if url.path == "/api/review-agents":
                    data = reviews.eligible_agents(db, account, kind, target_id)
                else:
                    review_id = skills.query_id(params["id"][0]) if "id" in params else None
                    data = reviews.read(db, account, review_id=review_id, kind=kind, target_id=target_id)
            self.send_json(200, data)
        except accounts.SignInRequired:
            self.send_json(401, {"error": "Sign in to continue."})
        except LookupError:
            self.send_json(404, {"error": "Review unavailable."})
        except sharing.AccessDenied:
            self.send_json(403, {"error": "This review target is unavailable."})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except storage.ERRORS as error:
            LOG.error("Review read failed (%s)", type(error).__name__)
            self.send_json(500, {"error": "Could not read reviews."})

    def read_skills(self, url):
        try:
            with library.connect(self.server.database) as db:
                storage.begin(db)
                account = self.require_account(db)
                if url.path == "/api/skills/default":
                    data = {"skill": skills.DEFAULT_SKILL}
                elif url.path == "/api/skills":
                    params = parse_qs(url.query, keep_blank_values=True)
                    archived = params.get("archived", ["0"])[0]
                    if archived not in ("0", "1"):
                        raise ValueError("Use archived=0 or archived=1.")
                    data = skills.list_skills(
                        db, account, query=params.get("q", [""])[0], tag=params.get("tag", [""])[0],
                        after=skills.query_id(params.get("after", [""])[0], optional=True), archived=archived == "1",
                    )
                else:
                    skill_id = skills.query_id(url.path.removeprefix("/api/skills/"))
                    data = {"skill": skills.detail(db, account, skill_id)}
            self.send_json(200, data)
        except accounts.SignInRequired:
            self.send_json(401, {"error": "Sign in to continue."})
        except LookupError:
            self.send_json(404, {"error": "Skill unavailable."})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except storage.ERRORS as error:
            LOG.error("Skill read failed (%s)", type(error).__name__)
            self.send_json(500, {"error": "Could not read skills."})

    def do_POST(self):
        if not self.origin_allowed():
            self.send_json(403, {"error": "Library origin required"})
            return
        if self.path == "/api/papers":
            self.upload_pdf()
            return
        if self.path == "/api/research-upload":
            self.upload_research_file()
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
            if self.path in account_routes.SESSION_ROUTES:
                account_routes.update_session(self, data)
                return
            if self.path == "/api/lookup":
                if "paper_id" in data:
                    paper_id = data["paper_id"]
                    if type(paper_id) is not int:
                        raise ValueError("Select a paper")
                    with library.connect(self.server.database) as db:
                        storage.begin(db)
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
            if self.path == "/api/detect-paper-metrics":
                paper_id = data.get("paper_id")
                if not reviews.valid_id(paper_id):
                    raise ValueError("Choose a paper.")
                keywords = pdf.detection_keywords(data.get("keywords", []))
                try:
                    result = pdf.detect_existing(self.server.database, paper_id, keywords,
                                                 get_account=self.require_account, size_limit=MAX_PDF_BYTES)
                except (subprocess.SubprocessError, OSError):
                    self.send_json(422, {"error": "Could not read or extract the verified PDF."})
                    return
                self.send_json(200, result)
                return
            with library.connect(self.server.database) as db:
                storage.begin(db, write=True)
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
        except storage.INTEGRITY_ERRORS:
            self.send_json(409, {"error": "A group already exists or a selected record is missing"})
        except storage.ERRORS as error:
            LOG.error("Database update failed (%s)", type(error).__name__)
            self.send_json(500, {"error": "Could not update the library database"})
        except RuntimeError as error:
            self.send_json(502, {"error": str(error)})
        except LookupError:
            errors = {"/api/skills": "Skill unavailable.", "/api/reviews": "Review unavailable."}
            self.send_json(404, {"error": errors.get(self.path, "Unknown route")})

    def upload_research_file(self):
        if self.headers.get_content_type() != "application/octet-stream":
            self.send_json(415, {"error": "Use application/octet-stream."})
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= size <= experiments.MAX_FILE_BYTES:
                raise ValueError("Choose a file of up to 100 MiB.")
            metadata = json.loads(unquote(self.headers.get("X-Research-Metadata", ""), errors="strict"))
            if not isinstance(metadata, dict):
                raise ValueError("Invalid artifact metadata.")
            with library.connect(self.server.database) as db:
                self.require_account(db)
            self.connection.settimeout(60)
            payload = self.rfile.read(size)
            if len(payload) != size:
                raise ValueError("Incomplete upload.")
            with library.connect(self.server.database) as db:
                storage.begin(db, write=True)
                item_id = experiments.save_item(db, self.require_account(db), metadata, payload)
            self.send_json(200, {"ok": True, "id": item_id})
        except accounts.SignInRequired:
            self.send_json(401, {"error": "Sign in to upload files."})
        except sharing.AccessDenied:
            self.send_json(403, {"error": "This item is unavailable."})
        except sharing.EditConflict as error:
            self.send_json(409, {"error": str(error)})
        except (ValueError, KeyError, OverflowError) as error:
            self.send_json(400, {"error": str(error)})
        except storage.ERRORS + (OSError,) as error:
            LOG.error("Research upload failed (%s)", type(error).__name__)
            self.send_json(500, {"error": "Could not save this file."})

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
            keyword_header = self.headers.get("X-Paper-Metric-Keywords")
            keywords = pdf.detection_keywords(json.loads(unquote(keyword_header, errors="strict"))) if keyword_header else ()
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
            result = import_pdf(self.server.database, filename, payload, account, audience, recipients, keywords=keywords)
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
        except storage.ERRORS + (OSError,) as error:
            LOG.error("PDF import failed (%s)", type(error).__name__)
            self.send_json(500, {"error": "Could not save the local PDF import"})

    def update(self, db, data):
        if self.path == "/api/ai/invitations":
            self.require_human(db)
            invite = ai_accounts.create_invite(db, data)
            origin = getattr(self.server, "public_url", None) or self.request_origin()
            return {**invite, "registration_url": origin + invite["registration_path"]}
        if self.path.startswith(ai_accounts.REGISTRATION_PREFIX):
            return ai_accounts.register(db, self.path.removeprefix(ai_accounts.REGISTRATION_PREFIX), data)
        if self.path == "/api/ai/challenge":
            return ai_accounts.challenge(db, data)
        if self.path == "/api/ai/login":
            return ai_accounts.login(db, data)
        if self.path == "/api/reviews":
            account = self.require_account(db)
            if data.get("action") == "create":
                return reviews.create(db, account, data)
            if data.get("action") == "complete":
                return reviews.complete(db, account, data)
            raise ValueError("Choose create or complete.")
        if self.path == "/api/skills":
            return {"skill": skills.save(db, self.require_account(db), data)}
        if self.path == "/api/research-goals":
            return goals.update(db, self.require_account(db), data)
        if self.path == "/api/research-findings":
            return findings.save(db, self.require_account(db), data)
        if self.path in ("/api/experiments", "/api/experiment-runs", "/api/research-items", "/api/research-grants", "/api/tool-jobs", "/api/approve-tool-job"):
            return experiment_routes.update(self, db, data)
        if self.path in ("/api/application-keys", "/api/revoke-key"):
            return account_routes.update_key(self, db, data)
        if self.path == "/api/groups":
            self.require_human(db)
            library.create_group(db, data.get("name"))
            return
        if self.path == "/api/documents":
            return document_routes.save(self, db, data)
        if self.path in ("/api/comments", "/api/delete-comment"):
            return comment_routes.update_comment(self, db, data)
        if self.path not in ("/api/paper-access", "/api/metadata", "/api/memberships", "/api/archive-paper",
                             "/api/paper-metrics", "/api/metric-editors", "/api/claim-paper"):
            raise LookupError
        return paper_routes.update_paper(self, db, data)



def serve(database, port, external_url=None):
    if not shutil.which("pdftotext"):
        LOG.warning("pdftotext is unavailable; PDF import and text extraction will fail")
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        server.database = database
        server.public_url = external_url
        server.google_config = google_signin.configuration(server.server_port, origin=external_url)
        stop = Event()
        worker = Thread(target=metadata_sync.run, args=(database, stop), daemon=True)
        worker.start()
        if external_url:
            print(f"Public Paper Library at {external_url}/ via reverse proxy.", flush=True)
        print(f"Paper library at http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--public-url", default=os.getenv("PAPER_PUBLIC_URL"),
                        help="Public HTTPS origin served through a local reverse proxy")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--import-csv", type=Path, help="Import a metrics CSV and exit")
    modes.add_argument("--invite-human", metavar="EMAIL", help="Issue a one-time browser signup code")
    modes.add_argument("--create-account", nargs=2, metavar=("USERNAME", "ROLE"))
    modes.add_argument("--set-account-role", nargs=2, metavar=("USERNAME", "ROLE"))
    modes.add_argument("--set-tool-approver", metavar="USERNAME", help="Authorize a trusted human to approve tool jobs")
    modes.add_argument("--register-tool", nargs=2, metavar=("USERNAME", "CONFIG_JSON"), help="Register a pinned tool owned by USERNAME")
    args = parser.parse_args()
    try:
        database = storage.configuration(args.database)
        library.initialize(database)
        if args.set_tool_approver:
            with library.connect(database) as db:
                storage.begin(db, write=True)
                account = db.execute(f"SELECT a.id,{accounts.ROLE_SQL.format(alias='a')} AS role FROM accounts a WHERE username=?", (args.set_tool_approver,)).fetchone()
                if not account or account['role'] != 'user':
                    raise ValueError("Approvers must be trusted human accounts.")
                db.execute("INSERT INTO tool_approvers VALUES (?) ON CONFLICT DO NOTHING", (account['id'],))
            print("Tool approver saved.")
            return
        if args.register_tool:
            username, config_file = args.register_tool
            config = json.loads(Path(config_file).read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("Tool configuration must be an object.")
            with library.connect(database) as db:
                storage.begin(db, write=True)
                owner = db.execute("SELECT id FROM accounts WHERE username=?", (username,)).fetchone()
                if not owner:
                    raise ValueError("Tool owner not found.")
                tool_id = tools_catalog.register(db, owner, config)
            print(f"Registered tool {tool_id}.")
            return
        if args.invite_human:
            with library.connect(database) as db:
                storage.begin(db, write=True)
                token = accounts.create_invite(db, args.invite_human)
            print(f"Invitation for {args.invite_human} (valid for 24 hours): {token}")
            return
        if args.create_account or args.set_account_role:
            username, role = args.create_account or args.set_account_role
            if args.create_account:
                password = getpass.getpass("Password: ")
                if password != getpass.getpass("Confirm password: "):
                    raise ValueError("Passwords do not match.")
            with library.connect(database) as db:
                storage.begin(db, write=True)
                if args.create_account:
                    accounts.create_account(db, username, password, role)
                else:
                    accounts.set_role(db, username, role)
            print(f"Saved account {username} ({role}).")
            return
        if args.import_csv:
            with args.import_csv.open(encoding="utf-8-sig", newline="") as stream:
                with library.connect(database) as db:
                    storage.begin(db, write=True)
                    count = library.import_csv(db, stream, args.import_csv.absolute().parent)
            print(f"Imported metrics for {count} paper path(s).")
            return
        serve(database, args.port, public_url(args.public_url) if args.public_url else None)
    except storage.ERRORS + (csv.Error, ValueError, OSError, EOFError) as error:
        parser.exit(1, f"Paper library: {error}\n")


if __name__ == "__main__":
    main()
