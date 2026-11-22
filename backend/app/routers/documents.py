import logging
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Document, ResearchProject, User
from app.schemas import DocumentResponse, DocumentSearchResult
from app.security import get_current_user, require_project_owner
from app.services.documents import SUPPORTED_EXTENSIONS
from app.services.processing import reprocess_document
from app.services.storage import (
    delete_document as delete_stored_document,
    is_remote_storage_path,
    read_document,
    store_document,
)

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)


@router.get(
    "/api/projects/{project_id}/documents/search",
    response_model=list[DocumentSearchResult],
)
def search_documents(
    project_id: uuid.UUID,
    q: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = q.strip()
    if len(query) < 2 or len(query) > 200:
        raise HTTPException(status_code=422, detail="Search text must be between 2 and 200 characters.")
    require_project_owner(db, project_id, user.user_id)
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    documents = db.scalars(
        select(Document)
        .where(
            Document.project_id == project_id,
            Document.extracted_text.is_not(None),
            Document.extracted_text.ilike(f"%{escaped}%", escape="\\"),
        )
        .order_by(Document.uploaded_at.desc())
        .limit(25)
    ).all()
    results = []
    for document in documents:
        full_text = document.extracted_text or ""
        position = full_text.casefold().find(query.casefold())
        start = max(0, position - 180)
        excerpt = full_text[start : position + len(query) + 220].strip()
        results.append({"document": document, "excerpt": excerpt})
    return results


@router.get("/api/projects/{project_id}/documents", response_model=list[DocumentResponse])
def list_documents(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    return list(
        db.scalars(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.uploaded_at.desc())
        ).all()
    )


@router.get("/api/documents/{document_id}/download")
def download_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    project = db.get(ResearchProject, document.project_id)
    if project is None or project.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not is_remote_storage_path(document.storage_path):
        path = Path(document.storage_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Stored document file is missing.")
        return FileResponse(path, filename=document.filename, media_type="application/octet-stream")
    try:
        contents = read_document(document.storage_path)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Cloud document storage is unavailable; retry the download."
        ) from exc
    return Response(
        content=contents,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename)}"
        },
    )


@router.post(
    "/api/projects/{project_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    original_name = Path((file.filename or "").replace("\\", "/")).name.strip()
    extension = Path(original_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Upload a PDF, DOCX, TXT, or Markdown file.")
    data = await file.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {get_settings().max_upload_mb} MB upload limit.",
        )
    document_id = uuid.uuid4()
    try:
        storage_path = store_document(
            project_id,
            document_id,
            extension,
            data,
            file.content_type,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Cloud document storage is unavailable; retry the upload."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    document = Document(
        document_id=document_id,
        project_id=project_id,
        filename=original_name[:255],
        file_type=extension.lstrip("."),
        storage_path=storage_path,
        file_size=len(data),
        processing_status="processing",
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            delete_stored_document(storage_path)
        except (httpx.HTTPError, RuntimeError, ValueError) as cleanup_error:
            logger.exception(
                "Could not remove uploaded object after document metadata insert failed"
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Document metadata could not be saved and cloud file cleanup failed; "
                    "contact support."
                ),
            ) from cleanup_error
        raise
    db.refresh(document)
    background_tasks.add_task(_process_saved_document, document_id)
    return document


def _process_saved_document(document_id: uuid.UUID) -> None:
    from app.main import app

    factory = app.state.research_session_factory
    with factory() as db:
        document = db.get(Document, document_id)
        if document is not None:
            reprocess_document(db, document)


@router.post("/api/documents/{document_id}/reprocess", response_model=DocumentResponse)
def reprocess(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    project = db.get(ResearchProject, document.project_id)
    if project is None or project.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    document.processing_status = "processing"
    document.processing_error = None
    db.commit()
    background_tasks.add_task(_process_saved_document, document_id)
    return document


@router.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    project = db.get(ResearchProject, document.project_id)
    if project is None or project.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    db.delete(document)
    db.commit()
    try:
        delete_stored_document(document.storage_path)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Document was removed from the project, but its stored file could not be deleted.",
        ) from exc
