#!/usr/bin/env python3
"""Extract metric candidates from PDF text into a CSV using fixed rules."""

import argparse
import csv
import hashlib
import os
import re
import sqlite3
import subprocess
from decimal import Decimal
from pathlib import Path

from paper_library import FIELDS, connect, initialize, store

NUMBER = r"[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+−-]?\d+)?"
UNIT_GROUPS = {
    "energy efficiency": r"[TGMP]OPS\s*(?:/|per\s+)\s*W",
    "area efficiency": r"[TGMP]OPS\s*(?:/|per\s+)\s*mm(?:²|\^?2)",
    "throughput": r"[TGMP]OPS|(?:frames|images|tokens|samples|inferences)\s*/\s*s|FPS",
    "power": r"[mµμun]?W",
    "energy": r"[fnpµμum]?J(?:\s*/\s*(?:inference|op|MAC|bit))?",
    "latency": r"(?:ms|[µμun]s|seconds?)",
    "area": r"(?:mm|[µμu]m)(?:²|\^?2)",
    "frequency": r"[kMG]?Hz",
    "bandwidth": r"[kMGT]B\s*/\s*s|[kMGT]bps",
    "percentage": "%",
}
UNIT_LOOKUP = {f"u{index}": metric for index, metric in enumerate(UNIT_GROUPS)}
UNITS = "|".join(
    f"(?P<{group}>{pattern})"
    for group, pattern in zip(UNIT_LOOKUP, UNIT_GROUPS.values())
)
MEASUREMENT = re.compile(
    rf"(?<![\w.,])(?P<first>{NUMBER})"
    rf"(?:\s*(?:[–—-]|\bto\b)\s*(?P<second>{NUMBER}))?\s*"
    rf"(?:{UNITS})(?![\w/])",
    re.IGNORECASE,
)
PERCENT_LABEL = re.compile(
    r"\b(?:top[- ]?[15](?:[- ]accuracy)?|accuracy|precision|recall|"
    r"f1(?: score)?|utilization|error rate)\b", re.IGNORECASE,
)
CONDITION = re.compile(
    r"\b(?:INT\s*\d+|FP\s*\d+|BF\s*\d+|\d+\s*[- ]?bit|"
    r"batch size\s*[:=]?\s*\d+|peak|average|mean|measured|simulated)\b",
    re.IGNORECASE,
)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def spreadsheet_text(value):
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def candidates(page):
    text = " ".join(page.split())
    for sentence in SENTENCE_BREAK.split(text):
        for match in MEASUREMENT.finditer(sentence):
            group = next(group for group in UNIT_LOOKUP if match[group] is not None)
            metric = UNIT_LOOKUP[group]
            # Limit evidence and qualifiers to nearby text, including on pages
            # where columns or table cells lack sentence punctuation.
            nearby = sentence[max(0, match.start() - 90):match.end() + 90].strip()
            if metric == "percentage":
                label = PERCENT_LABEL.search(nearby)
                if not label:
                    continue
                metric = label.group().lower()
            unit = re.sub(r"\s+", "", match[group].replace("μ", "µ"))
            conditions = list(dict.fromkeys(item.group() for item in CONDITION.finditer(nearby)))
            values = [(match["first"], "")]
            if match["second"] is not None:
                values = [(match["first"], "range start"), (match["second"], "range end")]
            for value, endpoint in values:
                number = Decimal(value.replace(",", "").replace("−", "-"))
                qualifiers = ", ".join(conditions + ([endpoint] if endpoint else []))
                yield metric, str(number), unit, qualifiers, nearby


def extract_pdf(path, payload=None):
    source = "-" if payload is not None else str(path.absolute())
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", source, "-"],
        input=payload, capture_output=True, timeout=60, check=True,
    )
    pages = result.stdout.decode("utf-8").split("\f")
    rows = dict.fromkeys(
        (page_number, *row)
        for page_number, page in enumerate(pages, start=1)
        for row in candidates(page)
    )
    return rows, any(page.strip() for page in pages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF files or symbolic links")
    parser.add_argument("--output", type=Path, help="New local CSV file")
    parser.add_argument("--database", type=Path, help="SQLite library file")
    args = parser.parse_args()
    if not args.output and not args.database:
        parser.error("Specify --output, --database, or both")
    if args.output and (args.output.exists() or args.output.is_symlink()):
        parser.error("Choose a new output file")

    if args.output and args.database and args.output.resolve() == args.database.resolve():
        parser.error("The CSV and database must have different paths")
    rows = {}
    imports = []
    skipped = 0
    for pdf in args.pdfs:
        try:
            payload = pdf.read_bytes() if args.database else None
            paper_rows, has_text = extract_pdf(pdf, payload)
        except (OSError, subprocess.SubprocessError, UnicodeError) as error:
            parser.exit(1, f"PDF extraction failed ({type(error).__name__}).\n")
        if not has_text:
            skipped += 1
        for page, metric, value, unit, conditions, evidence in paper_rows:
            row = (
                spreadsheet_text(str(pdf)), page, spreadsheet_text(metric),
                value, spreadsheet_text(unit), spreadsheet_text(conditions),
                spreadsheet_text(evidence),
            )
            rows[row] = None

        if payload is not None:
            imports.append((pdf, paper_rows, hashlib.sha256(payload).hexdigest()))

    try:
        if args.database:
            initialize(args.database)
            with connect(args.database) as db:
                for pdf, paper_rows, digest in imports:
                    store(db, pdf, paper_rows, digest)
        if args.output:
            with open(args.output, "x", encoding="utf-8", newline="",
                      opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
                writer = csv.writer(output)
                writer.writerow(FIELDS)
                writer.writerows(rows)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Cannot save results: {error}\n")
    print(f"Saved {len(rows)} metric candidate(s). PDFs without extractable text: {skipped}.")


if __name__ == "__main__":
    main()
