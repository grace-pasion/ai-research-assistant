import csv
import io
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, get_literature_db
from app.models import (
    Author,
    Document,
    DocumentPaper,
    Paper,
    PaperAuthor,
    ProjectPaper,
    ResearchProject,
    SavedPaperSearch,
    SearchQuery,
    SearchQueryResult,
    SystematicReviewWorkspace,
    Notification,
    User,
)
from app.schemas import (
    DocumentResponse,
    PaperResponse,
    PaperImportResponse,
    PaperScreeningResponse,
    PaperScreeningBulkResponse,
    PaperScreeningBulkUpdate,
    PaperScreeningCounts,
    PaperScreeningUpdate,
    SystematicReviewResponse,
    SystematicReviewUpdate,
    SavedPaperSearchAlertsCheckResponse,
    SavedPaperSearchCreate,
    SavedPaperSearchResponse,
    SavedPaperSearchRunResponse,
    SavedPaperSearchUpdate,
    PaperSearchResponse,
)
from app.security import get_current_user, require_project_access
from app.services.academic_search import (
    OpenAccessPDFTooLarge,
    download_open_access_pdf,
    open_access_pdf_url,
    search_papers,
    upsert_paper,
)
from app.services.audit import record_activity
from app.services.bibliography import (
    Reference,
    format_references,
    parse_bibtex,
    parse_ris,
    save_references_to_project,
)
from app.services.processing import process_saved_document
from app.services.storage import delete_document as delete_stored_document
from app.services.storage import store_document

router = APIRouter(prefix="/api/projects/{project_id}/papers", tags=["academic papers"])
logger = logging.getLogger(__name__)
MAX_REFERENCE_IMPORT_BYTES = 5 * 1024 * 1024


def _paper_response(
    paper: Paper,
    literature_db: Session,
    saved: bool = False,
    screening_status: str = "unread",
    screening_note: str = "",
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
        screening_status=screening_status,
        screening_note=screening_note,
    )


@router.get("", response_model=list[PaperResponse])
def list_saved_papers(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    saved = db.scalars(
        select(ProjectPaper)
        .where(ProjectPaper.project_id == project_id)
        .order_by(ProjectPaper.added_at.desc())
    ).all()
    paper_ids = [item.paper_id for item in saved]
    if not paper_ids:
        return []
    screening = {item.paper_id: item for item in saved}
    papers = literature_db.scalars(select(Paper).where(Paper.paper_id.in_(paper_ids))).all()
    papers_by_id = {paper.paper_id: paper for paper in papers}
    return [
        _paper_response(
            papers_by_id[paper_id],
            literature_db,
            saved=True,
            screening_status=screening[paper_id].screening_status,
            screening_note=screening[paper_id].screening_note,
        )
        for paper_id in paper_ids
        if paper_id in papers_by_id
    ]


@router.post("/import", response_model=PaperImportResponse, status_code=status.HTTP_201_CREATED)
async def import_reference_file(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    extension = Path((file.filename or "").replace("\\", "/")).suffix.casefold()
    if extension not in {".ris", ".bib", ".bibtex"}:
        raise HTTPException(status_code=415, detail="Choose a RIS or BibTeX (.bib/.bibtex) file.")
    content = await file.read(MAX_REFERENCE_IMPORT_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The bibliography file is empty.")
    if len(content) > MAX_REFERENCE_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Bibliography files are limited to 5 MB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="The bibliography file must be UTF-8 encoded.") from exc
    try:
        references = parse_ris(text) if extension == ".ris" else parse_bibtex(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = save_references_to_project(db, literature_db, project_id, references)
    record_activity(
        db,
        user.user_id,
        "paper.references_imported",
        {
            "format": extension.lstrip("."),
            "added_count": result["added_count"],
            "duplicate_count": result["duplicate_count"],
        },
    )
    db.commit()
    return result


@router.get("/export")
def export_reference_file(
    project_id: uuid.UUID,
    format: Literal["ris", "bibtex"] = Query(default="ris"),
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    papers = list_saved_papers(project_id, db, literature_db, user)
    references = [
        Reference(
            title=paper.title,
            authors=tuple(author.author_name for author in paper.authors),
            year=paper.publication_year,
            doi=paper.doi,
            venue=paper.venue,
            abstract=paper.abstract,
            url=paper.paper_url,
            citation_key=f"ref{paper.paper_id.hex}",
        )
        for paper in papers
    ]
    filename = "references.ris" if format == "ris" else "references.bib"
    media_type = (
        "application/x-research-info-systems" if format == "ris" else "application/x-bibtex"
    )
    return Response(
        content=format_references(references, format),
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _screening_counts(db: Session, project_id: uuid.UUID) -> PaperScreeningCounts:
    grouped_counts = db.execute(
        select(ProjectPaper.screening_status, func.count())
        .where(ProjectPaper.project_id == project_id)
        .group_by(ProjectPaper.screening_status)
    ).all()
    counts = {status: 0 for status in ("unread", "undecided", "include", "exclude")}
    total = sum(count for _, count in grouped_counts)
    for screening_status, count in grouped_counts:
        if screening_status in counts:
            counts[screening_status] = count
    reviewed = counts["undecided"] + counts["include"] + counts["exclude"]
    return PaperScreeningCounts(
        total=total,
        unread=counts["unread"],
        undecided=counts["undecided"],
        include=counts["include"],
        exclude=counts["exclude"],
        reviewed=reviewed,
    )


def _systematic_review_response(
    db: Session,
    project_id: uuid.UUID,
    workspace: SystematicReviewWorkspace | None,
) -> SystematicReviewResponse:
    return SystematicReviewResponse(
        review_question=workspace.review_question if workspace else "",
        protocol=workspace.protocol if workspace else "",
        updated_at=workspace.updated_at if workspace else None,
        screening_counts=_screening_counts(db, project_id),
    )


@router.get("/review", response_model=SystematicReviewResponse)
def get_systematic_review(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    workspace = db.get(SystematicReviewWorkspace, project_id)
    return _systematic_review_response(db, project_id, workspace)


@router.put("/review", response_model=SystematicReviewResponse)
def save_systematic_review(
    project_id: uuid.UUID,
    payload: SystematicReviewUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    workspace = db.get(SystematicReviewWorkspace, project_id)
    expected = payload.expected_updated_at
    current = workspace.updated_at if workspace else None
    if expected is not None and expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if expected != current:
        raise HTTPException(
            status_code=409,
            detail="This review protocol changed in another session. Reload the latest version before saving.",
        )

    if workspace is None:
        workspace = SystematicReviewWorkspace(
            project_id=project_id,
            review_question=payload.review_question,
            protocol=payload.protocol,
            updated_by=user.user_id,
        )
        db.add(workspace)
    else:
        result = db.execute(
            update(SystematicReviewWorkspace)
            .where(
                SystematicReviewWorkspace.project_id == project_id,
                SystematicReviewWorkspace.updated_at == workspace.updated_at,
            )
            .values(
                review_question=payload.review_question,
                protocol=payload.protocol,
                updated_by=user.user_id,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="This review protocol changed in another session. Reload the latest version before saving.",
            )

    record_activity(db, user.user_id, "systematic_review.saved")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This review protocol changed in another session. Reload the latest version before saving.",
        ) from None
    db.refresh(workspace)
    return _systematic_review_response(db, project_id, workspace)


def _safe_csv_cell(value: str | None) -> str:
    if value is None:
        return ""
    if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


@router.get("/review/export")
def export_systematic_review_csv(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    papers = list_saved_papers(project_id, db, literature_db, user)
    workspace = db.get(SystematicReviewWorkspace, project_id)
    counts = _screening_counts(db, project_id)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "record_type",
            "review_question",
            "protocol",
            "total_papers",
            "reviewed_papers",
            "unread_count",
            "undecided_count",
            "included_count",
            "excluded_count",
            "paper_id",
            "title",
            "authors",
            "publication_year",
            "doi",
            "url",
            "venue",
            "citation_count",
            "screening_status",
            "screening_note",
            "abstract",
        ]
    )
    writer.writerow(
        [
            "summary",
            _safe_csv_cell(workspace.review_question if workspace else ""),
            _safe_csv_cell(workspace.protocol if workspace else ""),
            counts.total,
            counts.reviewed,
            counts.unread,
            counts.undecided,
            counts.include,
            counts.exclude,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    for paper in papers:
        writer.writerow(
            [
                "paper",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                paper.paper_id,
                _safe_csv_cell(paper.title),
                _safe_csv_cell(", ".join(author.author_name for author in paper.authors)),
                paper.publication_year if paper.publication_year is not None else "",
                _safe_csv_cell(paper.doi),
                _safe_csv_cell(paper.paper_url),
                _safe_csv_cell(paper.venue),
                paper.citation_count if paper.citation_count is not None else "",
                paper.screening_status,
                _safe_csv_cell(paper.screening_note),
                _safe_csv_cell(paper.abstract),
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="systematic-review-report.csv"'
        },
    )


@router.get("/screening/export")
def export_screening_csv(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    papers = list_saved_papers(project_id, db, literature_db, user)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "title",
            "authors",
            "publication_year",
            "doi",
            "url",
            "venue",
            "citation_count",
            "screening_status",
            "screening_note",
            "abstract",
        ]
    )
    for paper in papers:
        writer.writerow(
            [
                _safe_csv_cell(paper.title),
                _safe_csv_cell(", ".join(author.author_name for author in paper.authors)),
                paper.publication_year if paper.publication_year is not None else "",
                _safe_csv_cell(paper.doi),
                _safe_csv_cell(paper.paper_url),
                _safe_csv_cell(paper.venue),
                paper.citation_count if paper.citation_count is not None else "",
                paper.screening_status,
                _safe_csv_cell(paper.screening_note),
                _safe_csv_cell(paper.abstract),
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="screening.csv"'},
    )


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
    require_project_access(db, project_id, user.user_id)
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


def _saved_paper_search(
    db: Session,
    project_id: uuid.UUID,
    saved_search_id: uuid.UUID,
    user_id: uuid.UUID,
) -> SavedPaperSearch:
    saved_search = db.scalar(
        select(SavedPaperSearch).where(
            SavedPaperSearch.saved_search_id == saved_search_id,
            SavedPaperSearch.project_id == project_id,
            SavedPaperSearch.user_id == user_id,
        )
    )
    if saved_search is None:
        raise HTTPException(status_code=404, detail="Saved search not found in this project.")
    return saved_search


@router.get("/saved-searches", response_model=list[SavedPaperSearchResponse])
def list_saved_searches(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    return db.scalars(
        select(SavedPaperSearch)
        .where(
            SavedPaperSearch.project_id == project_id,
            SavedPaperSearch.user_id == user.user_id,
        )
        .order_by(SavedPaperSearch.created_at.desc())
    ).all()


@router.post(
    "/saved-searches",
    response_model=SavedPaperSearchResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_saved_search(
    project_id: uuid.UUID,
    payload: SavedPaperSearchCreate,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    query = db.scalar(
        select(SearchQuery).where(
            SearchQuery.query_id == payload.query_id,
            SearchQuery.project_id == project_id,
        )
    )
    if query is None:
        raise HTTPException(status_code=404, detail="Search history entry not found in this project.")

    existing = db.scalar(
        select(SavedPaperSearch).where(
            SavedPaperSearch.project_id == project_id,
            SavedPaperSearch.user_id == user.user_id,
            SavedPaperSearch.query_text == query.query_text,
            SavedPaperSearch.api_provider == query.api_provider,
        )
    )
    if existing is not None:
        if payload.alert_enabled and not existing.alert_enabled:
            existing.alert_enabled = True
            db.commit()
        return existing

    result_ids = db.scalars(
        select(SearchQueryResult.paper_id).where(SearchQueryResult.query_id == query.query_id)
    ).all()
    papers = literature_db.scalars(select(Paper).where(Paper.paper_id.in_(result_ids))).all()
    saved_search = SavedPaperSearch(
        project_id=project_id,
        user_id=user.user_id,
        query_text=query.query_text,
        api_provider=query.api_provider,
        alert_enabled=payload.alert_enabled,
        seen_external_ids=[paper.external_paper_id for paper in papers],
        last_checked_at=datetime.now(timezone.utc),
    )
    db.add(saved_search)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(SavedPaperSearch).where(
                SavedPaperSearch.project_id == project_id,
                SavedPaperSearch.user_id == user.user_id,
                SavedPaperSearch.query_text == query.query_text,
                SavedPaperSearch.api_provider == query.api_provider,
            )
        )
        if existing is None:
            raise
        if payload.alert_enabled and not existing.alert_enabled:
            existing.alert_enabled = True
            db.commit()
        return existing
    return saved_search


@router.patch("/saved-searches/{saved_search_id}", response_model=SavedPaperSearchResponse)
def update_saved_search(
    project_id: uuid.UUID,
    saved_search_id: uuid.UUID,
    payload: SavedPaperSearchUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    saved_search = _saved_paper_search(db, project_id, saved_search_id, user.user_id)
    saved_search.alert_enabled = payload.alert_enabled
    db.commit()
    return saved_search


@router.delete("/saved-searches/{saved_search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_search(
    project_id: uuid.UUID,
    saved_search_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    saved_search = _saved_paper_search(db, project_id, saved_search_id, user.user_id)
    db.delete(saved_search)
    db.commit()


def _run_saved_paper_search(
    project_id: uuid.UUID,
    saved_search: SavedPaperSearch,
    db: Session,
    literature_db: Session,
    user: User,
) -> tuple[PaperSearchResponse, int, int]:
    saved_search.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    result = search(
        project_id,
        saved_search.query_text,
        saved_search.api_provider,
        10,
        db,
        literature_db,
        user,
    )
    current_ids = {paper.external_paper_id for paper in result.results}
    seen_ids = set(saved_search.seen_external_ids)
    new_result_count = len(current_ids - seen_ids)
    saved_search.seen_external_ids = sorted(seen_ids | current_ids)
    notifications_created = 0
    if saved_search.alert_enabled and new_result_count:
        db.add(
            Notification(
                recipient_id=user.user_id,
                actor_id=user.user_id,
                kind="saved_search_alert",
                project_id=project_id,
                details={
                    "query": saved_search.query_text,
                    "provider": saved_search.api_provider,
                    "new_result_count": new_result_count,
                },
            )
        )
        notifications_created = 1
    db.commit()
    return result, new_result_count, notifications_created


@router.post(
    "/saved-searches/{saved_search_id}/run",
    response_model=SavedPaperSearchRunResponse,
)
def run_saved_search(
    project_id: uuid.UUID,
    saved_search_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    saved_search = _saved_paper_search(db, project_id, saved_search_id, user.user_id)
    result, new_result_count, _ = _run_saved_paper_search(
        project_id, saved_search, db, literature_db, user
    )
    return SavedPaperSearchRunResponse(
        **result.model_dump(),
        new_result_count=new_result_count,
    )


@router.post(
    "/saved-searches/check-alerts",
    response_model=SavedPaperSearchAlertsCheckResponse,
)
def check_saved_search_alerts(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    due_searches = db.scalars(
        select(SavedPaperSearch)
        .where(
            SavedPaperSearch.project_id == project_id,
            SavedPaperSearch.user_id == user.user_id,
            SavedPaperSearch.alert_enabled.is_(True),
            (SavedPaperSearch.last_checked_at.is_(None))
            | (SavedPaperSearch.last_checked_at <= cutoff),
        )
        .order_by(SavedPaperSearch.last_checked_at.asc())
        .limit(10)
    ).all()
    notifications_created = 0
    for saved_search in due_searches:
        _, _, new_notifications = _run_saved_paper_search(
            project_id, saved_search, db, literature_db, user
        )
        notifications_created += new_notifications
    return SavedPaperSearchAlertsCheckResponse(
        checked_count=len(due_searches),
        notifications_created=notifications_created,
    )


@router.post("/{paper_id}/save", status_code=status.HTTP_204_NO_CONTENT)
def save_paper(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
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
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if db.get(ProjectPaper, (project_id, paper_id)) is None:
                raise


@router.delete("/{paper_id}/save", status_code=status.HTTP_204_NO_CONTENT)
def unsave_paper(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    relation = db.get(ProjectPaper, (project_id, paper_id))
    if relation is not None:
        db.delete(relation)
        record_activity(db, user.user_id, "paper.removed")
        db.commit()


@router.post(
    "/{paper_id}/full-text",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def import_open_access_full_text(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    if db.get(ProjectPaper, (project_id, paper_id)) is None:
        raise HTTPException(status_code=404, detail="Saved paper not found.")
    paper = literature_db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Academic paper not found.")

    existing = db.scalar(
        select(Document)
        .join(DocumentPaper, DocumentPaper.document_id == Document.document_id)
        .where(
            Document.project_id == project_id,
            DocumentPaper.paper_id == paper_id,
            DocumentPaper.relationship_type == "full_text",
        )
        .order_by(Document.uploaded_at.desc())
    )
    if existing is not None:
        retry = existing.processing_status not in {"processing", "ready", "needs_api_key"}
        if existing.processing_status == "needs_api_key":
            openai_key = get_settings().openai_api_key
            retry = bool(openai_key and openai_key.get_secret_value().strip())
        if retry:
            existing.processing_status = "processing"
            existing.processing_error = None
            db.commit()
            background_tasks.add_task(process_saved_document, existing.document_id)
        return existing

    try:
        pdf_url = open_access_pdf_url(paper)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Could not check OpenAlex for open-access full text."
        ) from exc
    if pdf_url is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No open-access PDF was found for this paper. You can upload a copy you have "
                "access to from the Documents section."
            ),
        )

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    try:
        contents = download_open_access_pdf(pdf_url, max_bytes)
    except OpenAccessPDFTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="The open-access PDF could not be downloaded or was not a valid PDF.",
        ) from exc

    document_id = uuid.uuid4()
    title = re.sub(r"[^\w.-]+", "_", paper.title, flags=re.UNICODE).strip("._")[:200]
    filename = f"{title or 'open-access-paper'}.pdf"
    try:
        storage_path = store_document(
            project_id,
            document_id,
            ".pdf",
            contents,
            "application/pdf",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Cloud document storage is unavailable; retry the import."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    document = Document(
        document_id=document_id,
        project_id=project_id,
        filename=filename,
        file_type="pdf",
        storage_path=storage_path,
        file_size=len(contents),
        processing_status="processing",
    )
    db.add(document)
    db.add(
        DocumentPaper(
            document_id=document_id,
            paper_id=paper_id,
            relationship_type="full_text",
        )
    )
    record_activity(db, user.user_id, "paper.full_text.imported")
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            delete_stored_document(storage_path)
        except (httpx.HTTPError, RuntimeError, ValueError) as cleanup_error:
            logger.exception("Could not remove imported PDF after metadata insert failed")
            raise HTTPException(
                status_code=502,
                detail=(
                    "Full-text metadata could not be saved and cloud file cleanup failed; "
                    "contact support."
                ),
            ) from cleanup_error
        raise
    db.refresh(document)
    background_tasks.add_task(process_saved_document, document_id)
    return document


@router.patch("/{paper_id}/screening", response_model=PaperScreeningResponse)
def update_paper_screening(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    payload: PaperScreeningUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    relation = db.get(ProjectPaper, (project_id, paper_id))
    if relation is None:
        raise HTTPException(status_code=404, detail="Saved paper not found in this project.")
    relation.screening_status = payload.screening_status
    relation.screening_note = payload.screening_note
    record_activity(
        db,
        user.user_id,
        "paper.screening.updated",
        {"status": payload.screening_status},
    )
    db.commit()
    return PaperScreeningResponse(
        screening_status=relation.screening_status,
        screening_note=relation.screening_note,
    )


@router.post("/screening/bulk", response_model=PaperScreeningBulkResponse)
def bulk_update_paper_screening(
    project_id: uuid.UUID,
    payload: PaperScreeningBulkUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    paper_ids = set(payload.paper_ids)
    relations = db.scalars(
        select(ProjectPaper).where(
            ProjectPaper.project_id == project_id,
            ProjectPaper.paper_id.in_(paper_ids),
        )
    ).all()
    if len(relations) != len(paper_ids):
        raise HTTPException(status_code=404, detail="One or more papers are not saved in this project.")

    for relation in relations:
        relation.screening_status = payload.screening_status
        if payload.screening_note is not None:
            relation.screening_note = payload.screening_note
    record_activity(
        db,
        user.user_id,
        "paper.screening.bulk_updated",
        {"status": payload.screening_status, "count": len(relations)},
    )
    db.commit()
    return PaperScreeningBulkResponse(updated_count=len(relations))

