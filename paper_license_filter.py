#!/usr/bin/env python3
"""Find Creative Commons license evidence in paper PDFs offline."""

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path


CC_URL = re.compile(
    r"https?://(?:www\.)?creativecommons\.org/"
    r"(?:licenses/(?:by(?:-nc)?(?:-sa|-nd)?)/[0-9]+\.[0-9]+"
    r"|publicdomain/zero/1\.0)\b",
    re.IGNORECASE,
)
CC_LABEL = re.compile(
    r"\b(?:CC[\s-]+BY(?:[\s-]+NC)?(?:[\s-]+(?:SA|ND))?"
    r"|CC[\s-]*0|Creative Commons (?:Attribution[\w -]*? (?:[0-9]+\.[0-9]+)"
    r"|licen[cs]e))\b(?:\s+[0-9]+\.[0-9]+)?",
    re.IGNORECASE,
)
def has_cc_evidence(path):
    try:
        extraction = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            timeout=60,
            check=True,
        )
        content = extraction.stdout.decode("utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False

    for page in content.split("\f"):
        normalized = " ".join(page.split())
        if CC_URL.search(normalized) or CC_LABEL.search(normalized):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Create local symbolic links to PDFs with Creative Commons license evidence."
    )
    parser.add_argument("inputs", type=Path, nargs="+", help="PDF files or directories to scan recursively")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("cc-papers"),
        help="New directory for symbolic links (default: cc-papers)",
    )
    args = parser.parse_args()
    if shutil.which("pdftotext") is None:
        parser.error("pdftotext is required (install Poppler, e.g. poppler-utils on Ubuntu)")

    paths = set()
    for entry in args.inputs:
        if entry.is_dir():
            paths.update(path.resolve() for path in entry.rglob("*")
                         if path.suffix.lower() == ".pdf" and path.is_file() and not path.is_symlink())
        elif entry.is_file() and entry.suffix.lower() == ".pdf":
            paths.add(entry.resolve())
        else:
            parser.error(f"Expected a PDF or directory: {entry}")
    if not paths:
        parser.error("No PDFs found")

    try:
        args.output.mkdir()
    except OSError as error:
        parser.error(f"Cannot create a new output directory: {error}")

    linked = 0
    for path in sorted(paths):
        if not has_cc_evidence(path):
            continue

        link = args.output / path.name
        number = 2
        while os.path.lexists(link):
            link = args.output / f"{path.stem}-{number}{path.suffix}"
            number += 1
        try:
            link.symlink_to(os.path.relpath(path, args.output.resolve()))
        except OSError as error:
            parser.exit(1, f"Cannot create symbolic link {link}: {error}\n")
        linked += 1

    print(f"Created {linked} symbolic link(s) in {args.output}")


if __name__ == "__main__":
    main()
