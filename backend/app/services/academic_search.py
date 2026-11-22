import math
import re
from typing import Any

import httpx
from fastapi import HTTPException
from openai import APIError, OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Author, Paper, PaperAuthor

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


def _rerank_semantically(query: str, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
        return papers
    if not papers:
        return papers

    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    descriptions = [
        f"{paper['title']}\n{paper.get('abstract') or ''}".strip() for paper in papers
    ]
    try:
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=[query, *descriptions],
        )
    except APIError as exc:
        raise HTTPException(
            status_code=502,
            detail="OpenAI semantic paper ranking failed. Try again later.",
        ) from exc

    vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    query_vector = vectors[0]
    query_norm = math.sqrt(sum(value * value for value in query_vector))
    query_terms = list(
        dict.fromkeys(
            term for term in re.findall(r"\w+", query.casefold()) if len(term) > 2
        )
    )
    paper_tokens = [
        (
            set(re.findall(r"\w+", paper["title"].casefold())),
            set(re.findall(r"\w+", (paper.get("abstract") or "").casefold())),
        )
        for paper in papers
    ]
    document_frequencies = {
        term: sum(term in title or term in abstract for title, abstract in paper_tokens)
        for term in query_terms
    }
    term_weights = {
        term: math.log((len(papers) + 1) / (frequency + 1)) + 1
        for term, frequency in document_frequencies.items()
    }
    total_term_weight = sum(term_weights.values())

    def similarity(paper_index: int) -> float:
        paper_vector = vectors[paper_index + 1]
        paper_norm = math.sqrt(sum(value * value for value in paper_vector))
        if not query_norm or not paper_norm:
            return 0.0
        dot = sum(left * right for left, right in zip(query_vector, paper_vector))
        return dot / (query_norm * paper_norm)

    def lexical_relevance(paper_index: int) -> float:
        title_terms, abstract_terms = paper_tokens[paper_index]
        if not total_term_weight:
            return 0.0
        matched_weight = sum(
            term_weights[term]
            * (1.0 if term in title_terms else 0.8 if term in abstract_terms else 0.0)
            for term in query_terms
        )
        return matched_weight / total_term_weight

    return [
        paper
        for _, paper in sorted(
            enumerate(papers),
            key=lambda item: (
                -(similarity(item[0]) + 0.35 * lexical_relevance(item[0])),
                item[0],
            ),
        )
    ]


def search_papers(query: str, provider: str, limit: int) -> list[dict[str, Any]]:
    settings = get_settings()
    headers = {"User-Agent": "AIResearchAssistant/1.0 (mailto:contact@example.com)"}
    candidate_limit = min(max(limit * 3, limit), 75)
    with httpx.Client(timeout=20, headers=headers) as client:
        if provider == "openalex":
            params: dict[str, Any] = {"search": query, "per-page": candidate_limit}
            if settings.openalex_email:
                params["mailto"] = settings.openalex_email
            response = client.get(OPENALEX_URL, params=params)
            response.raise_for_status()
            items = response.json().get("results", [])
            papers = [paper for item in items if (paper := normalize_openalex(item))]
            return _rerank_semantically(query, papers)[:limit]
        if provider == "crossref":
            response = client.get(
                CROSSREF_URL,
                params={"query.bibliographic": query, "rows": candidate_limit},
            )
            response.raise_for_status()
            items = response.json().get("message", {}).get("items", [])
            papers = [paper for item in items if (paper := normalize_crossref(item))]
            return _rerank_semantically(query, papers)[:limit]
    raise ValueError(f"Unsupported academic search provider: {provider}")


def upsert_paper(literature_db: Session, data: dict[str, Any]) -> Paper:
    paper = literature_db.scalar(
        select(Paper).where(
            Paper.api_provider == data["api_provider"],
            Paper.external_paper_id == data["external_paper_id"],
        )
    )
    if paper is None:
        paper = Paper(
            external_paper_id=data["external_paper_id"],
            api_provider=data["api_provider"],
            title=data["title"],
        )
        literature_db.add(paper)
        literature_db.flush()
    for field in (
        "title",
        "abstract",
        "publication_year",
        "doi",
        "paper_url",
        "venue",
        "citation_count",
    ):
        value = data.get(field)
        if value is not None:
            setattr(paper, field, value)
    for order, author_data in enumerate(data.get("authors") or []):
        external_id = (author_data.get("id") or author_data["name"]).strip()
        if not external_id:
            continue
        author = literature_db.scalar(
            select(Author).where(
                Author.api_provider == data["api_provider"],
                Author.external_author_id == external_id,
            )
        )
        if author is None:
            author = Author(
                author_name=author_data["name"][:255],
                external_author_id=external_id[:255],
                api_provider=data["api_provider"],
            )
            literature_db.add(author)
            literature_db.flush()
        relation = literature_db.get(PaperAuthor, (paper.paper_id, author.author_id))
        if relation is None:
            literature_db.add(
                PaperAuthor(paper_id=paper.paper_id, author_id=author.author_id, author_order=order)
            )
        else:
            relation.author_order = order
    return paper
