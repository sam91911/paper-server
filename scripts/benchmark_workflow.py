"""Measure human browsing and agent traffic against a disposable local library."""

import argparse
import json
import math
import os
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from time import perf_counter, sleep
from urllib.parse import quote
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from paper_app import accounts, agent_goals, database, experiments, library, pdf
from paper_app.server import Handler
from scripts.research_pilot import methods_pdf


@contextmanager
def disposable_target(root, postgres_url):
    if not postgres_url:
        yield root / "benchmark.sqlite3"
        return

    from psycopg import connect, sql
    from psycopg.conninfo import make_conninfo

    name = f"paper_benchmark_{uuid4().hex}"
    identifier = sql.Identifier(name)
    with connect(postgres_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(identifier))
        try:
            yield database.PostgreSQL(make_conninfo(postgres_url, dbname=name), root / "pdfs")
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(identifier))


def seed(target, args):
    library.initialize(target)
    with library.connect(target) as db:
        owner = {"id": accounts.create_account(db, "researcher", uuid4().hex, "user"), "role": "user"}
        cookie = accounts.start_session(db, owner["id"], None)
    paper_id = pdf.import_pdf(target, "methods.pdf", methods_pdf(), owner, "local")["paper_id"]
    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for index in range(args.archive_files):
            bundle.writestr(f"src/score{index}.py", "print(0.8)\n")
    with library.connect(target) as db:
        db.executemany("INSERT INTO papers(path,title) VALUES (?,?)", (
            (f"synthetic/paper-{index}.pdf", f"Synthetic paper {index}") for index in range(args.papers - 1)
        ))
        experiment = experiments.save_experiment(db, owner, {"title": "Reference experiment"})
        archive_item = experiments.save_item(db, owner, {
            "experiment_id": experiment, "kind": "code", "title": "Source", "filename": "source.zip",
        }, archive.getvalue())
        version = db.execute("SELECT id FROM research_versions WHERE item_id=?", (archive_item,)).fetchone()[0]
        agents = []
        for index in range(args.agents):
            name = f"agent-{index}"
            actor = {"id": accounts.create_account(db, name, uuid4().hex, "local"), "role": "local"}
            key = accounts.create_key(db, actor["id"], "Benchmark")
            agent_goals.update(db, owner, {
                "action": "create", "agents": [name], "objective": "Reproduce the score",
                "acceptance_criteria": "Upload the result", "request_id": uuid4().hex,
            })
            run_experiment = experiments.save_experiment(db, actor, {"title": f"Agent experiment {index}"})
            run_id = experiments.save_run(db, actor, {
                "experiment_id": run_experiment, "title": "Local run", "status": "complete",
            })
            agents.append((key, run_experiment, run_id))
    return cookie, paper_id, experiment, version, agents


class BenchmarkHandler(Handler):
    def log_message(self, format, *args):
        if format.startswith("request_metric ") or format.startswith("code "):
            super().log_message(format, *args)


def request(port, label, path, headers, body=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=30)
    started = perf_counter()
    try:
        connection.request("GET" if body is None else "POST", path, body=body, headers=headers)
        reply = connection.getresponse()
        reply.read()
        result = reply.status
    except (OSError, HTTPException) as error:
        result = type(error).__name__
    finally:
        connection.close()
    return label, result, (perf_counter() - started) * 1000


def run(target, args):
    cookie, paper_id, experiment, version, agents = seed(target, args)
    human_headers = {"Cookie": f"{accounts.COOKIE}={cookie}"}
    archive = f"/research-versions/{version}"
    browsing = [
        ("paper_catalog", "/api/paper-catalog?facets=1"),
        ("paper_detail", f"/api/paper-detail?paper_id={paper_id}"),
        ("paper_pdf", f"/papers/{paper_id}/source.pdf"),
        ("experiment_detail", f"/api/experiment-detail?id={experiment}"),
        ("archive_list", f"{archive}/entries"),
        ("archive_preview", f"{archive}/entry?path=src%2Fscore0.py"),
    ]
    payload = bytes(args.upload_kib * 1024)
    with ThreadingHTTPServer(("127.0.0.1", 0), BenchmarkHandler) as server:
        server.database, server.public_url, server.google_config = target, None, None
        server.request_metrics = args.request_metrics
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            port = server.server_port
            clients = args.users + args.agents
            start = Event()

            def browse():
                start.wait()
                samples = []
                for index in range(args.rounds):
                    if index:
                        sleep(args.pause_ms / 1000)
                    for label, path in browsing:
                        samples.append(request(port, label, path, human_headers))
                return samples

            def check_goals(key, destination, run_id):
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                upload_headers = {**headers, "Content-Type": "application/octet-stream",
                                  "X-Research-Metadata": quote(json.dumps({
                                      "experiment_id": destination, "run_id": run_id, "kind": "data",
                                      "title": "Synthetic result", "filename": "result.bin",
                                  }))}
                start.wait()
                samples = []
                for index in range(args.rounds):
                    if index:
                        sleep(args.pause_ms / 1000)
                    samples.append(request(port, "goal_list", "/api/agent-goals", headers))
                    samples.append(request(port, "heartbeat", "/api/ai/heartbeat", headers, b"{}"))
                    if index % args.upload_every == 0:
                        samples.append(request(port, "artifact_upload", "/api/research-upload", upload_headers, payload))
                return samples

            with ThreadPoolExecutor(max_workers=clients) as pool:
                try:
                    futures = [pool.submit(browse) for _ in range(args.users)]
                    futures.extend(pool.submit(check_goals, *agent) for agent in agents)
                    started = perf_counter()
                finally:
                    start.set()
                samples = [sample for future in futures for sample in future.result()]
                return samples, perf_counter() - started
        finally:
            server.shutdown()
            thread.join()


def report(samples, elapsed):
    grouped = defaultdict(list)
    for label, status, latency in samples:
        grouped[label].append((status, latency))
    counts = defaultdict(int)
    errors = 0
    print(f"{len(samples)} requests in {elapsed:.2f} s ({len(samples) / elapsed:.1f} req/s)")
    print(f"{'Operation':<22} {'Requests':>8} {'Errors':>8} {'p50 ms':>10} {'p95 ms':>10} {'Max ms':>10}")
    for label, batch in sorted(grouped.items()):
        times = sorted(latency for _, latency in batch)
        failures = [status for status, _ in batch if status != 200]
        for status in failures:
            counts[(label, status)] += 1
        errors += len(failures)
        p50, p95 = (times[math.ceil(fraction * len(times)) - 1] for fraction in (.50, .95))
        print(f"{label:<22} {len(times):>8} {len(failures):>8} {p50:>10.2f} {p95:>10.2f} {times[-1]:>10.2f}")
    for (label, status), count in counts.items():
        print(f"{label}: {count} failed with {status}")
    return bool(errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true", help="Use PAPER_TEST_POSTGRES_URL to create a temporary database.")
    parser.add_argument("--users", type=int, default=4)
    parser.add_argument("--agents", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=10, help="Number of browsing or agent cycles per client.")
    parser.add_argument("--papers", type=int, default=1000)
    parser.add_argument("--archive-files", type=int, default=100)
    parser.add_argument("--upload-kib", type=int, default=256)
    parser.add_argument("--upload-every", type=int, default=3, help="Upload on the first agent round and every N rounds after.")
    parser.add_argument("--pause-ms", type=int, default=100, help="Delay between rounds for each client.")
    parser.add_argument("--request-metrics", action="store_true", help="Also emit the server's timing logs to stderr.")
    args = parser.parse_args()
    if min(args.users, args.agents, args.pause_ms) < 0 or not args.users + args.agents:
        parser.error("Client counts and pauses must be non-negative with at least one client.")
    if min(args.rounds, args.papers, args.upload_every) < 1:
        parser.error("Rounds, paper count, and upload interval must be positive.")
    if not 1 <= args.archive_files <= 5000 or not 1 <= args.upload_kib <= 102400:
        parser.error("Use 1–5,000 archive files and 1–102,400 KiB per upload.")
    postgres_url = os.getenv("PAPER_TEST_POSTGRES_URL") if args.postgres else None
    if args.postgres and not postgres_url:
        parser.error("Set PAPER_TEST_POSTGRES_URL to a PostgreSQL test instance.")
    print(f"{'PostgreSQL' if postgres_url else 'SQLite'}, {args.users} users, {args.agents} agents, "
          f"{args.rounds} rounds, {args.papers} papers, {args.archive_files} archive files, "
          f"{args.upload_kib} KiB uploads", flush=True)
    with tempfile.TemporaryDirectory() as tmp, disposable_target(Path(tmp), postgres_url) as target:
        return report(*run(target, args))


if __name__ == "__main__":
    raise SystemExit(main())
