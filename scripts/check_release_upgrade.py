"""Seed a database with the previous release and check access after upgrading."""

import argparse
import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from paper_app import accounts, library, pdf
from paper_app.server import Handler
from paper_client.review import LibraryClient, LibraryError

sys.path.append(str(Path(__file__).resolve().parent))
from research_pilot import methods_pdf


def seed(database, fixture):
    library.initialize(database)
    with library.connect(database) as db:
        owner_id = accounts.create_account(db, "owner", "test owner password", "user")
        cloud_id = accounts.create_account(db, "cloud", "test cloud password", "cloud")
        keys = {name: accounts.create_key(db, account_id, "upgrade rehearsal")
                for name, account_id in (("owner", owner_id), ("cloud", cloud_id))}
    owner = {"id": owner_id, "role": "user"}
    paper = pdf.import_pdf(database, "upgrade-fixture.pdf", methods_pdf(), owner, "owner")["paper_id"]
    with library.connect(database) as db:
        library.save_metadata(db, paper, {"doi": "10.1234/upgrade", "title": "Upgrade fixture"})
        db.execute("INSERT INTO metrics(paper_id,page,metric,value,unit,conditions,evidence) "
                   "VALUES (?,1,'Accuracy','80','%','','Upgrade fixture evidence')", (paper,))
        library.save_comment(db, paper, "Shared before the upgrade", owner, audience="all",
                             location={"kind": "pdf", "id": paper, "position": 1})
        library.save_comment(db, paper, "Private before the upgrade", owner, audience="owner")
    fixture.write_text(json.dumps({"paper": paper, **keys}), encoding="utf-8")


def expect_unavailable(client, path):
    try:
        client.request(path)
    except LibraryError as error:
        if error.status == 404:
            return
        raise
    raise AssertionError(f"Unauthorized endpoint returned data: {path}")


def verify_access(origin, state):
    owner = LibraryClient(None, state["owner"], server_url=origin)
    cloud = LibraryClient(None, state["cloud"], server_url=origin)
    paper = state["paper"]
    detail = f"/api/paper-detail?paper_id={paper}"
    discussion = f"/api/paper-comments?paper_id={paper}"
    source = f"/papers/{paper}/source.pdf"
    assert owner.get_json("/api/health") == {"status": "ok"}
    assert owner.request(source) == methods_pdf()
    assert owner.get_json("/api/metric-page")["metrics"]
    assert len(owner.get_json(discussion)["comments"]) == 2
    expect_unavailable(cloud, detail)
    assert cloud.get_json(discussion)["comments"] == []
    owner.request("/api/paper-access", {"paper_id": paper, "audience": "owner", "metadata_audience": "all"})
    visible = cloud.get_json(detail)["paper"]
    assert (visible["title"], visible["doi"], visible["has_pdf"], visible["pdf_restricted"]) == (
        "Upgrade fixture", "10.1234/upgrade", 0, 1,
    )
    comments = cloud.get_json(discussion)["comments"]
    assert [comment["body"] for comment in comments] == ["Shared before the upgrade"]
    assert comments[0]["target_position"] is None
    expect_unavailable(cloud, source)
    expect_unavailable(cloud, f"{source}?download=1")
    assert cloud.get_json("/api/metric-page")["metrics"] == []


def check(database, fixture):
    library.initialize(database)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.database, server.public_url, server.google_config = database, None, None
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            verify_access(f"http://127.0.0.1:{server.server_port}", json.loads(fixture.read_text(encoding="utf-8")))
        finally:
            server.shutdown()
            worker.join()
    print("Upgrade preserved the reference, PDF, comments, and backend access boundaries.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("seed", "check"))
    parser.add_argument("database", type=Path)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    (seed if args.phase == "seed" else check)(args.database, args.fixture)
