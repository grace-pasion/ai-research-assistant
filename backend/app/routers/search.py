import re
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Author,
    CrossProjectSearchRecord,
    Document,
    Paper,
    PaperAuthor,
    ProjectInvitation,
    ProjectPaper,
    ResearchProject,
    TeamWorkspaceMembership,
    User,
)
from app.schemas import CrossProjectSearchRecordResponse, CrossProjectSearchResult
from app.security import get_current_user

router = APIRouter(tags=["search"])
MAX_SEARCH_RESULTS = 100
SEARCH_DB_BATCH_SIZE = 500
YEAR_METADATA_KEYS = {"year", "publication_year", "publication year"}
AUTHOR_METADATA_KEYS = {"author", "authors", "creator"}
PROJECT_LIBRARY_PROVIDER = "project_library"


def _escaped_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _metadata_values(metadata: dict[str, str], keys: set[str]) -> list[str]:
    return [
        value.strip()
        for key, value in metadata.items()
        if key.strip().casefold() in keys and value.strip()
    ]


def _document_authors(metadata: dict[str, str]) -> list[str]:
    authors = _metadata_values(metadata, AUTHOR_METADATA_KEYS)
    return [
        author.strip()
        for value in authors
        for author in re.split(r"\s*[;|]\s*", value)
        if author.strip()
    ]


def _document_year(metadata: dict[str, str]) -> int | None:
    for value in _metadata_values(metadata, YEAR_METADATA_KEYS):
        match = re.match(r"\s*(\d{4})\b", value)
        if match:
            year = int(match.group(1))
            if 1000 <= year <= 2100:
                return year
    return None


def _excerpt(text: str | None, query: str, *, fallback_length: int = 260) -> str | None:
    if not text:
        return None
    position = text.casefold().find(query.casefold())
    if position < 0:
        return text[:fallback_length].strip()
    start = max(0, position - 100)
    return text[start : position + len(query) + 160].strip()


def _batches(values: list[uuid.UUID]) -> Iterator[list[uuid.UUID]]:
    for start in range(0, len(values), SEARCH_DB_BATCH_SIZE):
        yield values[start : start + SEARCH_DB_BATCH_SIZE]


def _search_record_filters(
    project_id: uuid.UUID | None,
    source_type: str | None,
    author: str,
    year: int | None,
    tag: str,
    limit: int,
) -> dict[str, str | int]:
    filters: dict[str, str | int] = {"limit": limit}
    if project_id is not None:
        filters["project_id"] = str(project_id)
    if source_type is not None:
        filters["source_type"] = source_type
    if author:
        filters["author"] = author
    if year is not None:
        filters["year"] = year
    if tag:
        filters["tag"] = tag
    return filters


def _save_cross_project_search(
    db: Session,
    user_id: uuid.UUID,
    query: str,
    filters: dict[str, str | int],
    result_count: int,
) -> None:
    db.add(
        CrossProjectSearchRecord(
            user_id=user_id,
            query_text=query,
            provider=PROJECT_LIBRARY_PROVIDER,
            filters=filters,
            result_count=result_count,
            searched_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


@router.get(
    "/api/search/history",
    response_model=list[CrossProjectSearchRecordResponse],
)
def list_cross_project_search_history(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.scalars(
        select(CrossProjectSearchRecord)
        .where(CrossProjectSearchRecord.user_id == user.user_id)
        .order_by(
            CrossProjectSearchRecord.searched_at.desc(),
            CrossProjectSearchRecord.record_id.desc(),
        )
        .limit(limit)
    ).all()


@router.get("/api/search", response_model=list[CrossProjectSearchResult])
def search_across_projects(
    q: str = Query(min_length=2, max_length=200),
    project_id: uuid.UUID | None = None,
    source_type: Literal["document", "paper"] | None = None,
    author: str | None = Query(default=None, max_length=255),
    year: int | None = Query(default=None, ge=1000, le=2100),
    tag: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=MAX_SEARCH_RESULTS),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    query = q.strip()
    author_filter = (author or "").strip()
    tag_filter = (tag or "").strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search text must be at least 2 characters.")
    if author is not None and not author_filter:
        raise HTTPException(status_code=422, detail="Author filter cannot be blank.")
    if tag is not None and not tag_filter:
        raise HTTPException(status_code=422, detail="Tag filter cannot be blank.")

    visible_project_rows = db.execute(
        select(ResearchProject.project_id, ResearchProject.project_name).where(
            or_(
                ResearchProject.user_id == user.user_id,
                ResearchProject.team_workspace_id.in_(
                    select(TeamWorkspaceMembership.team_workspace_id).where(
                        TeamWorkspaceMembership.user_id == user.user_id
                    )
                ),
                ResearchProject.project_id.in_(
                    select(ProjectInvitation.project_id).where(
                        ProjectInvitation.invitee_id == user.user_id,
                        ProjectInvitation.status == "accepted",
                        ProjectInvitation.role.in_(("read", "comment", "edit")),
                    )
                ),
            )
        )
    ).all()
    project_names = {row.project_id: row.project_name for row in visible_project_rows}
    if project_id is not None and project_id not in project_names:
        raise HTTPException(status_code=404, detail="Research project not found.")

    filters = _search_record_filters(
        project_id, source_type, author_filter, year, tag_filter, limit
    )
    visible_project_ids = (
        [project_id] if project_id is not None else list(project_names)
    )
    if not visible_project_ids:
        if offset == 0:
            _save_cross_project_search(db, user.user_id, query, filters, 0)
        return []

    pattern = _escaped_pattern(query)
    query_folded = query.casefold()
    author_pattern = _escaped_pattern(author_filter) if author_filter else None
    results: list[CrossProjectSearchResult] = []

    if source_type in (None, "document"):
        documents = []
        for project_id_batch in _batches(visible_project_ids):
            documents.extend(
                db.scalars(
                    select(Document).where(
                        Document.project_id.in_(project_id_batch),
                        or_(
                            Document.filename.ilike(pattern, escape="\\"),
                            Document.extracted_text.ilike(pattern, escape="\\"),
                        ),
                    )
                ).all()
            )
        for document in documents:
            metadata = document.custom_metadata or {}
            authors = _document_authors(metadata)
            document_year = _document_year(metadata)
            tags = document.tags or []
            if tag_filter and not any(tag.casefold() == tag_filter.casefold() for tag in tags):
                continue
            if author_filter and not any(
                author_filter.casefold() in item.casefold() for item in authors
            ):
                continue
            if year is not None and document_year != year:
                continue
            text = document.extracted_text or ""
            if query_folded not in document.filename.casefold() and query_folded not in text.casefold():
                continue
            results.append(
                CrossProjectSearchResult(
                    project_id=document.project_id,
                    project_name=project_names[document.project_id],
                    source_type="document",
                    source_id=document.document_id,
                    title=document.filename,
                    excerpt=_excerpt(text, query),
                    authors=authors,
                    year=document_year,
                    tags=tags,
                )
            )

    if source_type in (None, "paper"):
        saved_relations = []
        for project_id_batch in _batches(visible_project_ids):
            saved_relations.extend(
                db.execute(
                    select(ProjectPaper, ResearchProject.project_name)
                    .join(ResearchProject, ResearchProject.project_id == ProjectPaper.project_id)
                    .where(ProjectPaper.project_id.in_(project_id_batch))
                ).all()
            )
        filtered_relations = [
            (relation, project_name)
            for relation, project_name in saved_relations
            if not tag_filter
            or any(tag.casefold() == tag_filter.casefold() for tag in (relation.tags or []))
        ]
        paper_ids = {relation.paper_id for relation, _ in filtered_relations}
        if paper_ids:
            paper_by_id: dict[uuid.UUID, Paper] = {}
            paper_authors: dict[uuid.UUID, list[str]] = {}
            for paper_id_batch in _batches(sorted(paper_ids)):
                query_author_ids = set(
                    literature_db.scalars(
                        select(PaperAuthor.paper_id)
                        .join(Author, Author.author_id == PaperAuthor.author_id)
                        .where(
                            PaperAuthor.paper_id.in_(paper_id_batch),
                            Author.author_name.ilike(pattern, escape="\\"),
                        )
                    ).all()
                )
                conditions = [
                    Paper.title.ilike(pattern, escape="\\"),
                    Paper.abstract.ilike(pattern, escape="\\"),
                    Paper.doi.ilike(pattern, escape="\\"),
                    Paper.venue.ilike(pattern, escape="\\"),
                ]
                if query_author_ids:
                    conditions.append(Paper.paper_id.in_(query_author_ids))
                paper_query = select(Paper).where(
                    Paper.paper_id.in_(paper_id_batch),
                    or_(*conditions),
                )
                if year is not None:
                    paper_query = paper_query.where(Paper.publication_year == year)
                if author_pattern:
                    author_match_ids = literature_db.scalars(
                        select(PaperAuthor.paper_id)
                        .join(Author, Author.author_id == PaperAuthor.author_id)
                        .where(
                            PaperAuthor.paper_id.in_(paper_id_batch),
                            Author.author_name.ilike(author_pattern, escape="\\"),
                        )
                    ).all()
                    if not author_match_ids:
                        paper_query = paper_query.where(False)
                    else:
                        paper_query = paper_query.where(Paper.paper_id.in_(author_match_ids))
                papers = literature_db.scalars(paper_query).all()
                paper_by_id.update({paper.paper_id: paper for paper in papers})
                if papers:
                    author_rows = literature_db.execute(
                        select(PaperAuthor.paper_id, Author.author_name)
                        .join(Author, Author.author_id == PaperAuthor.author_id)
                        .where(
                            PaperAuthor.paper_id.in_(
                                [paper.paper_id for paper in papers]
                            )
                        )
                        .order_by(PaperAuthor.author_order)
                    ).all()
                    for paper_id, author_name in author_rows:
                        paper_authors.setdefault(paper_id, []).append(author_name)
            for relation, project_name in filtered_relations:
                paper = paper_by_id.get(relation.paper_id)
                if paper is None:
                    continue
                authors = paper_authors.get(paper.paper_id, [])
                if author_filter and not any(
                    author_filter.casefold() in item.casefold() for item in authors
                ):
                    continue
                abstract = re.sub(r"<[^>]*>", " ", paper.abstract or "")
                results.append(
                    CrossProjectSearchResult(
                        project_id=relation.project_id,
                        project_name=project_name,
                        source_type="paper",
                        source_id=paper.paper_id,
                        title=paper.title,
                        excerpt=_excerpt(abstract, query),
                        authors=authors,
                        year=paper.publication_year,
                        tags=relation.tags or [],
                    )
                )

    results.sort(
        key=lambda result: (
            0 if result.title.casefold().startswith(query_folded) else 1,
            result.project_name.casefold(),
            result.title.casefold(),
            result.source_type,
            str(result.project_id),
            str(result.source_id),
        )
    )
    if offset == 0:
        _save_cross_project_search(db, user.user_id, query, filters, len(results))
    return results[offset : offset + limit]
