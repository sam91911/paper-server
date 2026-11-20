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
    event = work.get("event") or {}
    data = {
        "doi": work.get("DOI", ""),
        "title": first(work.get("title", [])),
        "authors": "; ".join(
            entry.get("name") or " ".join(filter(None, (entry.get("given"), entry.get("family"))))
            for entry in work.get("author", [])
        ),
        "year": str(year),
        "venue": first(work.get("container-title") or []) or event.get("name", ""),
        "publisher": work.get("publisher", ""),
        "source": "Crossref",
        "short_venue": first(work.get("short-container-title") or []) or event.get("acronym", ""),
    }
    data["venue_group"] = venue_group(data)
    return data


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


def parse_year(value):
    if value is None or value == "":
        return None
    if type(value) not in (int, str) or not re.fullmatch(r"[1-9][0-9]{3}", str(value)):
        raise ValueError("Enter publication years as four digits.")
    return int(value)


def crossref_papers(query, publisher="", year_from=None, year_to=None):
    filters = ["type:journal-article", "type:proceedings-article"]
    if year_from is not None:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to is not None:
        filters.append(f"until-pub-date:{year_to}-12-31")
    params = {
        "query.title": query,
        "rows": 100,
        "select": "DOI,title,publisher,container-title,short-container-title,published,issued,event",
        "filter": ",".join(filters),
    }
    if publisher:
        params["query.publisher-name"] = publisher
    return get_message("?" + urlencode(params), timeout=30)["items"]


def venue_group(work):
    venue = work["venue"]
    short = work.get("short_venue", "")
    normalized = f"{venue} {short}".lower()
    if "journal of solid-state circuits" in normalized or re.search(r"\bjssc\b", normalized):
        return "JSSC"
    if "international solid-state circuits conference" in normalized or re.search(r"\bisscc\b", normalized):
        return "ISSCC"
    return re.sub(r"\b(?:19|20)\d{2}\b", "", venue).strip(" -–") or short or "Unknown venue"


def matching_papers(papers, keyword_groups, publisher="", year_from=None, year_to=None):
    publisher_words = title_words(publisher)
    matches = {}
    for paper in papers:
        doi = paper.get("DOI", "").strip().lower()
        if not DOI.fullmatch(doi) or doi.startswith("10.48550/arxiv."):
            continue
        work = candidate(paper)
        if not any(group <= title_words(work["title"]) for group in keyword_groups):
            continue
        if publisher_words and not publisher_words <= title_words(work["publisher"] or ""):
            continue
        if year_from is not None or year_to is not None:
            if not work["year"].isdigit():
                continue
            year = int(work["year"])
            if (year_from is not None and year < year_from) or (year_to is not None and year > year_to):
                continue
        work["doi"] = doi
        matches.setdefault(doi, work)
    return sorted(matches.values(), key=lambda work: (
        (work["publisher"] or "Unknown publisher").casefold(),
        work["venue_group"].casefold(),
        -(int(work["year"]) if work["year"].isdigit() else 0),
        work["title"].casefold(), work["doi"],
    ))


def search_papers(topic, keywords, publisher="", year_from=None, year_to=None):
    if not isinstance(publisher, str) or len(publisher.strip()) > 160:
        raise ValueError("Enter a publisher name of up to 160 characters.")
    publisher = publisher.strip()
    if publisher and not title_words(publisher):
        raise ValueError("Enter a publisher name.")
    year_from = parse_year(year_from)
    year_to = parse_year(year_to)
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("The first publication year must be at or before the last.")

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
            for paper in crossref_papers(query, publisher, year_from, year_to)
        )
        return matching_papers(papers, queries, publisher, year_from, year_to)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise RuntimeError(f"Crossref search failed: {error}") from error
