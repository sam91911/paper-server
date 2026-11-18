"""Retrieve bibliographic candidates without sending local paper content."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import urlopen

DOI = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)


def first(values):
    return values[0] if values else ""


def candidate(work):
    date = work.get("published") or work.get("issued") or {}
    year = first(first(date.get("date-parts", [])) or [])
    return {
        "doi": work.get("DOI", ""),
        "title": first(work.get("title", [])),
        "authors": "; ".join(
            entry.get("name") or " ".join(filter(None, (entry.get("given"), entry.get("family"))))
            for entry in work.get("author", [])
        ),
        "year": str(year),
        "venue": first(work.get("container-title", [])),
        "publisher": work.get("publisher", ""),
        "source": "Crossref",
    }


def lookup(kind, query):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError("Enter a DOI or title of up to 500 characters")
    query = query.strip()
    if kind == "doi":
        query = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", query, flags=re.I)
        if not DOI.fullmatch(query):
            raise ValueError("Enter a valid DOI, such as 10.1109/example")
        suffix = "/" + quote(query, safe="")
    elif kind == "title":
        suffix = "?" + urlencode({"query.title": query, "rows": 5})
    else:
        raise ValueError("Choose DOI or title lookup")
    try:
        with urlopen("https://api.crossref.org/works" + suffix, timeout=10) as response:
            message = json.load(response)["message"]
        return [candidate(work) for work in (message["items"] if kind == "title" else [message])]
    except HTTPError as error:
        if error.code == 404:
            return []
        raise RuntimeError(f"Crossref returned HTTP {error.code}. Try again later.") from error
    except (URLError, TimeoutError, OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise RuntimeError("Crossref is unavailable or returned an unreadable response.") from error
