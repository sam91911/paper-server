"""Import references from a selected Zotero CSL JSON export."""

from . import library, sharing


def field(item, name):
    value = item.get(name)
    return value.strip() if isinstance(value, str) else ""


def metadata(item):
    if not isinstance(item, dict) or not isinstance(item.get("type"), str):
        raise ValueError("Choose a Zotero CSL JSON export containing bibliographic items.")
    names = item.get("author")
    authors = []
    if isinstance(names, list):
        for name in names:
            if isinstance(name, dict):
                authors.append(field(name, "literal") or " ".join(
                    part for part in (field(name, "given"), field(name, "family")) if part))
    issued = item.get("issued")
    dates = issued.get("date-parts") if isinstance(issued, dict) else None
    year = ""
    if isinstance(dates, list) and dates and isinstance(dates[0], list) and dates[0]:
        year = str(dates[0][0]) if type(dates[0][0]) in (int, str) else ""
    return {
        "title": field(item, "title"), "doi": field(item, "DOI"), "source_url": field(item, "URL"),
        "authors": "; ".join(filter(None, authors)), "year": year, "venue": field(item, "container-title"),
        "publisher": field(item, "publisher"), "source": "Zotero",
    }


def import_references(db, account, data):
    items = data.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("Export 1 to 200 selected items as CSL JSON.")
    audience = sharing.validate_audience(data.get("metadata_audience", "owner"))
    results = []
    for item in items:
        reference = metadata(item)
        matches = library.visible_doi_matches(db, account, reference["doi"]) if reference["doi"] else []
        if matches:
            results.append({"paper_id": matches[0]["id"], "existing": True})
        else:
            paper_id = library.create_paper_reference(db, account, {**reference, "metadata_audience": audience})
            results.append({"paper_id": paper_id, "existing": False})
    return {"items": results}
