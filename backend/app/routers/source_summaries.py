import hashlib
import html
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Document,
    DocumentPaper,
    Paper,
    ProjectPaper,
    ProjectSourceSummary,
    User,
)
from app.schemas import ProjectSourceSummaryRequest, ProjectSourceSummaryResponse
from app.security import get_current_user, require_project_access
from app.services.source_summarization import generate_source_summary

router = APIRouter(tags=["source-summaries"])


def _read_document_source(
    db: Session,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
) -> tuple[str, str]:
    document = db.scalar(
        select(Document)
        .where(
            Document.document_id == document_id,
            Document.project_id == project_id,
        )
        .with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Source document not found in this project.")
    if document.processing_status != "ready":
        raise HTTPException(status_code=409, detail="The document is still being processed.")
    if not document.extracted_text or not document.extracted_text.strip():
        raise HTTPException(status_code=409, detail="No readable text is available for this document.")
    return document.filename, document.extracted_text


def _read_paper_source(
    db: Session,
    literature_db: Session,
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
) -> tuple[str, str]:
    saved_paper = db.scalar(
        select(ProjectPaper)
        .where(
            ProjectPaper.project_id == project_id,
            ProjectPaper.paper_id == paper_id,
        )
        .with_for_update()
    )
    if saved_paper is None:
        raise HTTPException(status_code=404, detail="Saved paper not found in this project.")

    paper = literature_db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Saved paper not found.")

    imported_document = db.scalar(
        select(Document)
        .join(DocumentPaper, DocumentPaper.document_id == Document.document_id)
        .where(
            Document.project_id == project_id,
            DocumentPaper.paper_id == paper_id,
            DocumentPaper.relationship_type == "full_text",
            Document.processing_status == "ready",
            Document.extracted_text.is_not(None),
        )
        .order_by(Document.uploaded_at.desc(), Document.document_id.desc())
        .limit(1)
    )
    source_text = (
        imported_document.extracted_text
        if imported_document is not None and imported_document.extracted_text
        else None
    )
    if not source_text and paper.abstract:
        source_text = html.unescape(re.sub(r"<[^>]*>", " ", paper.abstract)).strip()
    if not source_text:
        raise HTTPException(
            status_code=409,
            detail="This paper has no abstract or imported full text to summarize.",
        )
    return paper.title, source_text


def _summary_response(
    summary: ProjectSourceSummary,
    title: str,
    *,
    cached: bool,
) -> ProjectSourceSummaryResponse:
    return ProjectSourceSummaryResponse(
        source_type=summary.source_type,
        source_id=summary.source_id,
        title=title,
        summary=summary.summary_text,
        updated_at=summary.updated_at,
        cached=cached,
    )


@router.post(
    "/api/projects/{project_id}/source-summaries",
    response_model=ProjectSourceSummaryResponse,
)
def summarize_project_source(
    project_id: uuid.UUID,
    payload: ProjectSourceSummaryRequest,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    if payload.source_type == "document":
        title, source_text = _read_document_source(db, project_id, payload.source_id)
    else:
        title, source_text = _read_paper_source(
            db, literature_db, project_id, payload.source_id
        )

    source_hash = hashlib.sha256(
        f"{payload.source_type}\0{title}\0{source_text}".encode("utf-8")
    ).hexdigest()
    summary = db.scalar(
        select(ProjectSourceSummary)
        .where(
            ProjectSourceSummary.project_id == project_id,
            ProjectSourceSummary.source_type == payload.source_type,
            ProjectSourceSummary.source_id == payload.source_id,
        )
        .with_for_update()
    )
    if summary is not None and summary.source_hash == source_hash:
        return _summary_response(summary, title, cached=True)

    summary_text = generate_source_summary(title, source_text)
    if summary is None:
        summary = ProjectSourceSummary(
            project_id=project_id,
            source_type=payload.source_type,
            source_id=payload.source_id,
            source_hash=source_hash,
            summary_text=summary_text,
        )
        db.add(summary)
    else:
        summary.source_hash = source_hash
        summary.summary_text = summary_text

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent_summary = db.scalar(
            select(ProjectSourceSummary).where(
                ProjectSourceSummary.project_id == project_id,
                ProjectSourceSummary.source_type == payload.source_type,
                ProjectSourceSummary.source_id == payload.source_id,
            )
        )
        if concurrent_summary is not None and concurrent_summary.source_hash == source_hash:
            return _summary_response(concurrent_summary, title, cached=True)
        raise HTTPException(
            status_code=409,
            detail="The summary could not be saved. Please try again.",
        ) from exc

    return _summary_response(summary, title, cached=False)
