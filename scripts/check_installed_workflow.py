"""Check the installed server and the client distributed by its download endpoint."""

import json
import subprocess
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen
from uuid import uuid4

from paper_app import accounts, library
from paper_app.server import Handler
from paper_client.review import LibraryClient

# Python's isolated mode keeps the checkout off sys.path. Only load the fixture module here.
sys.path.append(str(Path(__file__).resolve().parent))
from research_pilot import methods_pdf


def check_workflow(origin, owner_key):
    owner = LibraryClient(None, owner_key, server_url=origin)

    def post(route, data):
        return json.loads(owner.request(route, data))

    assert owner.get_json("/api/health") == {"status": "ok"}
    for path in ("/agent-goals", "/assets/agent-goals.js"):
        assert owner.request(path)

    invitation = post("/api/ai/invitations", {"username": "worker", "role": "local"})
    with urlopen(invitation["client_download_url"], timeout=10) as response:
        archive = Path("paper-client.zip")
        archive.write_bytes(response.read())
    subprocess.run([sys.executable, "-m", "venv", "client"], check=True, timeout=60)
    python = Path("client/bin/python").absolute()
    subprocess.run([python, "-m", "pip", "install", str(archive)], check=True, timeout=120)
    identity = Path("worker.json").resolve()
    cli = [python, "-I", "-m", "paper_client.agent"]

    def run(*args, input=None):
        return subprocess.check_output([*cli, *args], input=input, timeout=30)

    def agent_request(route, data=None):
        args = ("request", "--identity", identity, route)
        if data is None:
            return json.loads(run(*args))
        return json.loads(run(*args, "--json-stdin", input=json.dumps(data).encode()))

    run("register", "--username", "worker", "--identity", identity,
        input=(invitation["registration_url"] + "\n").encode())
    assert json.loads(run("heartbeat", "--identity", identity, "--once"))["interval_seconds"] > 0

    # Use a synthetic PDF so the smoke test is deterministic and uses only the temporary library.
    paper = json.loads(owner._send("/api/papers", methods_pdf(), {
        "Content-Type": "application/pdf",
        "X-Paper-Filename": "benchmark.pdf",
        "X-Paper-Audience": "local",
    }))["paper_id"]
    skill = post("/api/skills", {
        "title": "Benchmark procedure", "markdown": "Record the local run and upload its output.", "recipients": ["worker"],
    })["skill"]
    route = "/api/agent-goals"
    goal = post(route, {
        "action": "create", "request_id": uuid4().hex, "agents": ["worker"],
        "objective": "Reproduce the synthetic benchmark", "acceptance_criteria": "Upload source and result.",
        "sources": [{"kind": "paper", "id": paper}], "required_skill_ids": [skill["id"]],
    })["goal"]
    fetched = agent_request(f"{route}?id={goal['id']}")["goal"]
    assert agent_request(fetched["required_skills"][0]["api_path"])["skill"]["markdown"] == skill["markdown"]
    goal = agent_request(route, {"action": "start", "id": goal["id"], "revision": goal["revision"],
                                 "request_id": uuid4().hex})["goal"]
    experiment = agent_request("/api/experiments", {"title": "Synthetic benchmark", "paper_id": paper})["id"]
    repository = Path("benchmark")
    repository.mkdir()
    source = repository / "score.py"
    source.write_text('print("score\\n0.8")\n', encoding="utf-8")
    git = ["git", "-C", repository]
    subprocess.run([*git, "init", "-q"], check=True, timeout=10)
    subprocess.run([*git, "add", source.name], check=True, timeout=10)
    subprocess.run([*git, "-c", "user.name=CI", "-c", "user.email=ci@example.invalid", "-c", "commit.gpgsign=false",
                    "commit", "-qm", "Add synthetic benchmark"], check=True, timeout=10)
    result = Path("results.csv")
    result.write_bytes(subprocess.check_output([python, source], timeout=10))
    run_id = agent_request("/api/experiment-runs", {
        "experiment_id": experiment, "title": "Local run", "methods": "python3 score.py", "status": "complete",
    })["id"]
    uploads = ("upload-artifact", "--identity", identity, "--experiment-id", str(experiment), "--run-id", str(run_id))
    snapshot = json.loads(run(*uploads, "--repository", repository, "--title", "Source"))["version_id"]
    output = json.loads(run(*uploads, "--file", result, "--title", "Results"))["version_id"]
    assert owner.get_json(f"/research-versions/{snapshot}/entries")["files"][0]["path"] == source.name
    assert owner.request(f"/research-versions/{output}/file") == b"score\n0.8\n"
    goal = agent_request(route, {
        "action": "submit", "id": goal["id"], "revision": goal["revision"], "request_id": uuid4().hex,
        "note": "Local run scored 0.8.", "evidence": [{"kind": "experiment", "id": experiment}],
    })["goal"]
    assert post(route, {"action": "accept", "id": goal["id"], "revision": goal["revision"],
                       "request_id": uuid4().hex})["goal"]["status"] == "completed"


def main():
    database = Path("smoke.sqlite3")
    library.initialize(database)
    with library.connect(database) as db:
        owner = accounts.create_account(db, "owner", "smoke test password", "user")
        owner_key = accounts.create_key(db, owner, "smoke test")
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.database, server.public_url, server.google_config = database, None, None
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            check_workflow(f"http://127.0.0.1:{server.server_port}", owner_key)
        finally:
            server.shutdown()
            thread.join()
    print("Installed client enrolled, fetched its goal skill, uploaded a local run, and completed the assignment.")


if __name__ == "__main__":
    main()
