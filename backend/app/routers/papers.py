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
from app.services.academic_search import search_papers, upsert_paper
from app.services.audit import record_activity

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
def search(
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
        results = search_papers(q.strip(), provider, limit)
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
    record_activity(
        db,
        user.user_id,
        "paper.searched",
        {"provider": provider, "result_count": len(results)},
    )
    literature_db.begin()
    try:
        papers = [upsert_paper(literature_db, result) for result in results]
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
        record_activity(db, user.user_id, "paper.saved")
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
        record_activity(db, user.user_id, "paper.removed")
        db.commit()

