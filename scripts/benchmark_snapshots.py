"""Measure snapshot size and time with disposable synthetic data."""
import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from paper_app import library


def measure(call):
    start = time.perf_counter()
    value = call()
    return time.perf_counter() - start, len(json.dumps(value).encode())


def benchmark_catalog(db, account):
    def snapshot():
        return library.snapshot(db, "paper-details", account, include_comments=False)

    def catalog():
        return dict(library.paper_catalog(db, account, facets=True), google_available=False)

    def detail():
        return library.paper_detail(db, account, 1)

    def comments():
        items = library.comment_snapshot(db, account, paper_id=1, root_limit=50)
        roots = [item["id"] for item in items if item["parent_id"] is None]
        return {"comments": items, "next_before": min(roots) if len(roots) == 50 else None}

    for label, readers in (
        ("Previous, no selection", [snapshot]),
        ("Catalog, no selection", [catalog]),
        ("Previous, preselected", [snapshot, comments]),
        ("Catalog, preselected", [catalog, detail, comments]),
    ):
        timings = []
        for _ in range(7):
            elapsed, size = zip(*(measure(reader) for reader in readers))
            timings.append(sum(elapsed))
        print(f"{label}: {len(readers)} JSON request(s), {sum(size):,} bytes, "
              f"{statistics.median(timings) * 1000:.2f} ms median")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--papers', type=int, default=1000)
    parser.add_argument('--comments-per-paper', type=int, default=10)
    parser.add_argument('--catalog', action='store_true', help='Compare previous and paged browser startup reads.')
    args = parser.parse_args()
    if args.papers < 1 or args.comments_per_paper < 1:
        parser.error('Counts must be positive.')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'benchmark.sqlite3'
        library.initialize(path)
        with library.connect(path) as db:
            db.execute("INSERT INTO accounts(username,password_hash,salt) VALUES ('owner',X'00',X'00')")
            db.executemany('INSERT INTO papers(id,path) VALUES (?,?)',
                           ((i, f'/tmp/{i}.pdf') for i in range(1, args.papers + 1)))
            db.executemany("INSERT INTO paper_access VALUES (?,1,'owner')",
                           ((i,) for i in range(1, args.papers + 1)))
            count = args.papers * args.comments_per_paper
            db.executemany("INSERT INTO comments(id,paper_id,body,audience) VALUES (?,?,?,'owner')",
                           ((i, (i - 1) // args.comments_per_paper + 1, 'A' * 200)
                            for i in range(1, count + 1)))
            db.executemany("INSERT INTO comment_authors VALUES (?,1,'user')", ((i,) for i in range(1, count + 1)))
            account = {'id': 1, 'role': 'user'}
            full = measure(lambda: library.snapshot(db, 'paper-details', account))
            scoped = measure(lambda: (library.snapshot(db, 'paper-details', account, include_comments=False),
                                      library.comment_snapshot(db, account, paper_id=1)))
            print(f'{args.papers} papers, {count} comments')
            print(f'Full snapshot: {full[0]:.3f} s, {full[1]:,} bytes')
            print(f'Scoped snapshot: {scoped[0]:.3f} s, {scoped[1]:,} bytes')
            if args.catalog:
                benchmark_catalog(db, account)


if __name__ == '__main__':
    main()
