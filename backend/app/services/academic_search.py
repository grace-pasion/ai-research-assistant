from datetime import datetime
from typing import Any

import httpx

from app.config import get_settings

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"


def _year(date_value: Any) -> int | None:
    if isinstance(date_value, int):
        return date_value if 1000 <= date_value <= 2100 else None
    if isinstance(date_value, str) and len(date_value) >= 4:
        try:
            year = int(date_value[:4])
            return year if 1000 <= year <= 2100 else None
        except ValueError:
            return None
    return None


def _openalex_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    positions = [position for word_positions in inverted.values() for position in word_positions]
    if not positions:
        return None
    words = [""] * (max(positions) + 1)
    for word, positions in inverted.items():
        for position in positions:
            words[position] = word
    return " ".join(words).strip() or None


def normalize_openalex(work: dict[str, Any]) -> dict[str, Any] | None:
    title = (work.get("title") or "").strip()
    external_id = (work.get("id") or "").rsplit("/", 1)[-1]
    if not title or not external_id:
        return None
    authors = []
    for item in work.get("authorships") or []:
        author = item.get("author") or {}
        if author.get("display_name"):
            authors.append(
                {
                    "id": (author.get("id") or "").rsplit("/", 1)[-1],
                    "name": author["display_name"].strip(),
                }
            )
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    return {
        "external_paper_id": external_id,
        "api_provider": "openalex",
        "title": title,
        "abstract": _openalex_abstract(work.get("abstract_inverted_index")),
        "publication_year": _year(work.get("publication_year")),
        "doi": work.get("doi"),
        "paper_url": primary_location.get("landing_page_url") or work.get("doi"),
        "venue": source.get("display_name"),
        "citation_count": work.get("cited_by_count"),
        "authors": authors,
    }


def normalize_crossref(work: dict[str, Any]) -> dict[str, Any] | None:
    title_values = work.get("title") or []
    title = (title_values[0] if title_values else "").strip()
    doi = work.get("DOI")
    if not title or not doi:
        return None
    date_parts = (
        (work.get("published-print") or work.get("published-online") or {}).get("date-parts") or []
    )
    date_value = date_parts[0][0] if date_parts and date_parts[0] else None
    authors = [
        {
            "id": f"{(author.get('given') or '').strip()} {(author.get('family') or '').strip()}".strip(),
            "name": f"{(author.get('given') or '').strip()} {(author.get('family') or '').strip()}".strip(),
        }
        for author in (work.get("author") or [])
        if (author.get("given") or author.get("family"))
    ]
    return {
        "external_paper_id": doi.lower(),
        "api_provider": "crossref",
        "title": title,
        "abstract": work.get("abstract"),
        "publication_year": _year(date_value),
        "doi": doi,
        "paper_url": work.get("URL") or f"https://doi.org/{doi}",
        "venue": (work.get("container-title") or [None])[0],
        "citation_count": work.get("is-referenced-by-count"),
        "authors": authors,
    }


async def search_papers(query: str, provider: str, limit: int) -> list[dict[str, Any]]:
    settings = get_settings()
    headers = {"User-Agent": "AIResearchAssistant/1.0 (mailto:contact@example.com)"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        if provider == "openalex":
            params: dict[str, Any] = {"search": query, "per-page": limit}
            if settings.openalex_email:
                params["mailto"] = settings.openalex_email
            response = await client.get(OPENALEX_URL, params=params)
            response.raise_for_status()
            items = response.json().get("results", [])
            return [paper for item in items if (paper := normalize_openalex(item))]
        if provider == "crossref":
            response = await client.get(
                CROSSREF_URL,
                params={"query.bibliographic": query, "rows": limit},
            )
            response.raise_for_status()
            items = response.json().get("message", {}).get("items", [])
            return [paper for item in items if (paper := normalize_crossref(item))]
    raise ValueError(f"Unsupported academic search provider: {provider}")
