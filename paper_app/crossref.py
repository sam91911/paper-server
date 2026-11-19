"""Retrieve bibliographic candidates without sending local paper content."""

import json
import re
import unicodedata
from html import unescape
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DOI = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
WORKS_URL = "https://api.crossref.org/works"


def get_message(suffix, timeout):
    request = Request(WORKS_URL + suffix, headers={"User-Agent": "LocalPaperLibrary/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)["message"]


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
        message = get_message(suffix, timeout=10)
        return [candidate(work) for work in (message["items"] if kind == "title" else [message])]
    except HTTPError as error:
        if error.code == 404:
            return []
        raise RuntimeError(f"Crossref returned HTTP {error.code}. Try again later.") from error
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise RuntimeError("Crossref is unavailable or returned an unreadable response.") from error


def title_words(value):
    value = unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unicodedata.normalize("NFKC", value).casefold()
    return frozenset(re.findall(r"[^\W_]+", value))


def crossref_papers(query):
    params = {
        "query.title": query,
        "rows": 100,
        "select": "DOI,title",
        "filter": "type:journal-article,type:proceedings-article",
    }
    return get_message("?" + urlencode(params), timeout=30)["items"]


def matching_papers(papers, keyword_groups):
    matches = {}
    for paper in papers:
        doi = paper.get("DOI", "").strip().lower()
        if not DOI.fullmatch(doi) or doi.startswith("10.48550/arxiv."):
            continue
        titles = paper.get("title") or []
        if not titles:
            continue
        title = titles[0]
        words = title_words(title)
        score = sum(group <= words for group in keyword_groups)
        if score:
            rank = (-score, title)
            matches[doi] = min(rank, matches.get(doi, rank))
    return [
        {"doi": doi, "title": matches[doi][1]}
        for doi in sorted(matches, key=lambda doi: (matches[doi][0], doi))
    ]


def search_papers(topic, keywords):
    if not isinstance(keywords, list) or len(keywords) > 10:
        raise ValueError("Provide up to 10 related keyword groups")
    queries = {}
    for value in [topic, *keywords]:
        if not isinstance(value, str) or len(value) > 500 or not (words := title_words(value)):
            raise ValueError("Each keyword group must contain words and be at most 500 characters")
        queries.setdefault(words, value.strip())
    try:
        papers = (
            paper
            for query in queries.values()
            for paper in crossref_papers(query)
        )
        return matching_papers(papers, queries)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise RuntimeError(f"Crossref search failed: {error}") from error
