import logging
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Document, ResearchProject, User
from app.schemas import (
    BulkDocumentUploadResponse,
    DocumentReaderResponse,
    DocumentResponse,
    DocumentSearchResult,
    LibraryMetadataUpdate,
)
from app.security import get_current_user, require_project_access
from app.services.audit import record_activity
from app.services.documents import SUPPORTED_EXTENSIONS
from app.services.processing import process_saved_document, reprocess_document
from app.services.storage import (
    delete_document as delete_stored_document,
    is_remote_storage_path,
    read_document,
    store_document,
)

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)
MAX_BULK_UPLOAD_COUNT = 20


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
    require_project_access(db, project_id, user.user_id)
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
    record_activity(db, user.user_id, "document.searched", {"result_count": len(results)})
    db.commit()
    return results


@router.get("/api/projects/{project_id}/documents", response_model=list[DocumentResponse])
def list_documents(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    return list(
        db.scalars(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.uploaded_at.desc())
        ).all()
    )


@router.patch(
    "/api/documents/{document_id}/metadata",
    response_model=DocumentResponse,
)
def update_document_metadata(
    document_id: uuid.UUID,
    payload: LibraryMetadataUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    require_project_access(db, document.project_id, user.user_id, "edit")
    document.tags = payload.tags
    document.custom_metadata = payload.metadata
    record_activity(
        db, user.user_id, "document.metadata.updated", project_id=document.project_id
    )
    db.commit()
    db.refresh(document)
    return document


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
    if project is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    require_project_access(db, project.project_id, user.user_id)
    if not is_remote_storage_path(document.storage_path):
        path = Path(document.storage_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Stored document file is missing.")
        record_activity(db, user.user_id, "document.downloaded")
        db.commit()
        return FileResponse(path, filename=document.filename, media_type="application/octet-stream")
    try:
        contents = read_document(document.storage_path)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Cloud document storage is unavailable; retry the download."
        ) from exc
    record_activity(db, user.user_id, "document.downloaded")
    db.commit()
    return Response(
        content=contents,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename)}"
        },
    )


@router.get("/api/documents/{document_id}/reader", response_model=DocumentReaderResponse)
def read_document_text(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    require_project_access(db, document.project_id, user.user_id)
    return DocumentReaderResponse(
        document_id=document.document_id,
        filename=document.filename,
        text=document.extracted_text or "",
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
    require_project_access(db, project_id, user.user_id, "edit")
    document = await _prepare_document_upload(project_id, file, db, user)
    storage_path = document.storage_path
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
    background_tasks.add_task(process_saved_document, document.document_id)
    return document


async def _prepare_document_upload(
    project_id: uuid.UUID,
    file: UploadFile,
    db: Session,
    user: User,
) -> Document:
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
        tags=[],
        custom_metadata={},
    )
    db.add(document)
    record_activity(
        db,
        user.user_id,
        "document.uploaded",
        {"file_type": extension.lstrip("."), "size_bytes": len(data)},
        project_id=project_id,
    )
    return document


@router.post(
    "/api/projects/{project_id}/documents/bulk",
    response_model=BulkDocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_documents(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    if not files:
        raise HTTPException(status_code=422, detail="Choose at least one document to upload.")
    if len(files) > MAX_BULK_UPLOAD_COUNT:
        raise HTTPException(
            status_code=413,
            detail=f"Upload no more than {MAX_BULK_UPLOAD_COUNT} documents at once.",
        )

    results = []
    documents = []
    for file in files:
        filename = Path((file.filename or "").replace("\\", "/")).name.strip()
        try:
            document = await _prepare_document_upload(project_id, file, db, user)
        except HTTPException as exc:
            results.append({"filename": filename, "document": None, "error": str(exc.detail)})
        else:
            documents.append(document)
            results.append({"filename": document.filename, "document": document, "error": None})

    if documents:
        try:
            db.commit()
        except Exception:
            db.rollback()
            cleanup_error = None
            for document in documents:
                try:
                    delete_stored_document(document.storage_path)
                except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                    logger.exception(
                        "Could not remove uploaded object after bulk document metadata insert failed"
                    )
                    cleanup_error = exc
            if cleanup_error is not None:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Document metadata could not be saved and cloud file cleanup failed; "
                        "contact support."
                    ),
                ) from cleanup_error
            raise

        for document in documents:
            db.refresh(document)
            background_tasks.add_task(process_saved_document, document.document_id)

    return {"results": results}


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
    if project is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    require_project_access(db, project.project_id, user.user_id, "edit")
    claimed = db.execute(
        update(Document)
        .where(
            Document.document_id == document_id,
            Document.processing_status != "processing",
        )
        .values(processing_status="processing", processing_error=None)
    )
    if not claimed.rowcount:
        db.rollback()
        current = db.get(Document, document_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        return current
    record_activity(
        db,
        user.user_id,
        "document.reprocessed",
        {"file_type": document.file_type},
        project_id=project.project_id,
    )
    db.commit()
    db.refresh(document)
    background_tasks.add_task(process_saved_document, document_id)
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
    if project is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    require_project_access(db, project.project_id, user.user_id, "edit")
    record_activity(
        db,
        user.user_id,
        "document.deleted",
        {"file_type": document.file_type},
        project_id=project.project_id,
    )
    db.delete(document)
    db.commit()
    try:
        delete_stored_document(document.storage_path)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Document was removed from the project, but its stored file could not be deleted.",
        ) from exc
