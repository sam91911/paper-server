"""Extract bounded, page-labelled review text from a PDF."""

import os
import re
import subprocess
import tempfile

PDF_LIMIT = 50 * 1024 * 1024
TEXT_LIMIT = 2 * 1024 * 1024


def page_count(pdf):
    info = subprocess.run(["pdfinfo", "-"], input=pdf, capture_output=True,
                          check=True, timeout=15, env={**os.environ, "LC_ALL": "C"})
    pages = re.search(rb"^Pages:\s+(\d+)", info.stdout, re.MULTILINE)
    if not pages:
        raise ValueError("Could not read the PDF page count.")
    return int(pages[1])


def extract(pdf, first=None, last=None):
    if b"%PDF-" not in pdf[:1024]:
        raise ValueError("The library did not return a PDF.")
    command = ["pdftotext", "-layout", "-enc", "UTF-8"]
    if first is not None:
        command.extend(("-f", str(first), "-l", str(last or first)))
    with tempfile.TemporaryFile() as output:
        subprocess.run([*command, "-", "-"], input=pdf, stdout=output,
                       stderr=subprocess.DEVNULL, check=True, timeout=60)
        output.seek(0)
        raw = output.read(TEXT_LIMIT + 1)
    if len(raw) > TEXT_LIMIT:
        raise ValueError("The extracted text is too large. Request a smaller page range.")
    pages = raw.decode("utf-8").split("\f")
    if pages[-1] == "":
        pages.pop()
    first = first or 1
    if last is not None and len(pages) != last - first + 1:
        raise ValueError("The PDF does not contain the requested page range.")
    if not any(page.strip() for page in pages):
        raise ValueError("The selected PDF pages have no extractable text.")
    return "\n\n".join(
        f"PDF page {number}\n\n{page.strip() or '[No extractable text]'}"
        for number, page in enumerate(pages, start=first)
    )
