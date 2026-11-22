import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Author,
    Paper,
    PaperAuthor,
    ProjectPaper,
    ResearchProject,
    SearchQuery,
    SearchQueryResult,
    User,
)
from app.schemas import PaperResponse, PaperSearchResponse
from app.security import get_current_user, require_project_owner
from app.services.academic_search import search_papers

router = APIRouter(prefix="/api/projects/{project_id}/papers", tags=["academic papers"])


def _paper_response(
    paper: Paper, literature_db: Session, saved: bool = False
) -> PaperResponse:
    relationships = literature_db.execute(
        select(Author.author_id, Author.author_name)
        .join(PaperAuthor, PaperAuthor.author_id == Author.author_id)
        .where(PaperAuthor.paper_id == paper.paper_id)
        .order_by(PaperAuthor.author_order)
    ).all()
    return PaperResponse(
        paper_id=paper.paper_id,
        external_paper_id=paper.external_paper_id,
        api_provider=paper.api_provider,
        title=paper.title,
        abstract=paper.abstract,
        publication_year=paper.publication_year,
        doi=paper.doi,
        paper_url=paper.paper_url,
        venue=paper.venue,
        citation_count=paper.citation_count,
        authors=[{"author_id": row.author_id, "author_name": row.author_name} for row in relationships],
        saved=saved,
    )


def _upsert_paper(literature_db: Session, data: dict) -> Paper:
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


@router.get("", response_model=list[PaperResponse])
def list_saved_papers(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    saved = db.scalars(
        select(ProjectPaper)
        .where(ProjectPaper.project_id == project_id)
        .order_by(ProjectPaper.added_at.desc())
    ).all()
    paper_ids = [item.paper_id for item in saved]
    if not paper_ids:
        return []
    papers = literature_db.scalars(select(Paper).where(Paper.paper_id.in_(paper_ids))).all()
    return [_paper_response(paper, literature_db, saved=True) for paper in papers]


@router.get("/search", response_model=PaperSearchResponse)
async def search(
    project_id: uuid.UUID,
    q: str = Query(min_length=2, max_length=500),
    provider: str = Query(default="openalex", pattern="^(openalex|crossref)$"),
    limit: int = Query(default=10, ge=1, le=25),
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    try:
        results = await search_papers(q.strip(), provider, limit)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{provider} search failed with HTTP {exc.response.status_code}. Try again later.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach {provider}; check your network and retry."
        ) from exc

    query = SearchQuery(project_id=project_id, query_text=q.strip(), api_provider=provider)
    db.add(query)
    literature_db.begin()
    try:
        papers = [_upsert_paper(literature_db, result) for result in results]
        literature_db.commit()
        db.flush()
        db.add_all(
            [
                SearchQueryResult(query_id=query.query_id, paper_id=paper.paper_id)
                for paper in papers
            ]
        )
        db.commit()
    except Exception:
        literature_db.rollback()
        db.rollback()
        raise
    return PaperSearchResponse(
        query_id=query.query_id,
        provider=provider,
        query=q.strip(),
        results=[_paper_response(paper, literature_db) for paper in papers],
    )


@router.post("/{paper_id}/save", status_code=status.HTTP_204_NO_CONTENT)
def save_paper(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    if literature_db.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail="Academic paper not found.")
    if db.get(ProjectPaper, (project_id, paper_id)) is None:
        db.add(
            ProjectPaper(
                project_id=project_id,
                paper_id=paper_id,
                relationship_type="saved",
            )
        )
        db.commit()


@router.delete("/{paper_id}/save", status_code=status.HTTP_204_NO_CONTENT)
def unsave_paper(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    relation = db.get(ProjectPaper, (project_id, paper_id))
    if relation is not None:
        db.delete(relation)
        db.commit()

