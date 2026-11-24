import json
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Iterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Conversation,
    Document,
    LatexWorkspace,
    Message,
    PythonWorkspace,
    PythonWorkspaceArtifact,
    ResearchProject,
    SystematicReviewWorkspace,
    User,
)
from app.routers.annotations import list_project_annotations
from app.routers.assistant import _conversation_detail
from app.routers.latex import DEFAULT_MAIN_TEX
from app.routers.papers import list_saved_papers
from app.security import get_current_user, require_project_access
from app.services.bibliography import Reference, format_references
from app.services.storage import read_document

router = APIRouter(tags=["project export"])
SPOOL_MAX_BYTES = 10 * 1024 * 1024
STREAM_CHUNK_SIZE = 64 * 1024


def _write_json(archive: zipfile.ZipFile, name: str, value: object) -> None:
    archive.writestr(
        name,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _safe_document_filename(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return basename if basename not in {"", ".", ".."} else "document"


def _stream_archive(archive_file) -> Iterator[bytes]:
    try:
        while chunk := archive_file.read(STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        archive_file.close()


@router.get("/api/projects/{project_id}/export")
def export_project_bundle(
    project_id: uuid.UUID,
    include_original_documents: bool = Query(default=False),
    include_conversations: bool = Query(default=False),
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    project: ResearchProject = require_project_access(db, project_id, user.user_id)
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.uploaded_at, Document.document_id)
        ).all()
    )
    papers = list_saved_papers(project_id, db, literature_db, user)
    annotations = list_project_annotations(project_id, "", db, literature_db, user)
    workspace = db.get(LatexWorkspace, project_id)
    python_workspace = db.get(PythonWorkspace, project_id)
    python_artifacts = list(
        db.scalars(
            select(PythonWorkspaceArtifact)
            .where(PythonWorkspaceArtifact.project_id == project_id)
            .order_by(PythonWorkspaceArtifact.filename)
        ).all()
    )
    review = db.get(SystematicReviewWorkspace, project_id)
    conversations = (
        list(
            db.scalars(
                select(Conversation)
                .where(
                    Conversation.project_id == project_id,
                    Conversation.user_id == user.user_id,
                )
                .order_by(Conversation.created_at, Conversation.conversation_id)
            ).all()
        )
        if include_conversations
        else []
    )

    paper_data = [paper.model_dump(mode="json") for paper in papers]
    project_paper_ids = {paper.paper_id for paper in papers}
    project_document_ids = {document.document_id for document in documents}
    bibtex_references = [
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
    document_index = [
        {
            "document_id": str(document.document_id),
            "filename": document.filename,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "processing_status": document.processing_status,
            "uploaded_at": document.uploaded_at.isoformat(),
            "original_included": include_original_documents,
        }
        for document in documents
    ]
    annotation_data = [annotation.model_dump(mode="json") for annotation in annotations]
    project_data = {
        "project_id": str(project.project_id),
        "project_name": project.project_name,
        "description": project.description,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }
    manifest = {
        "format": "fieldnotes-project-export",
        "format_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_by": str(user.user_id),
        "options": {
            "include_original_documents": include_original_documents,
            "include_conversations": include_conversations,
        },
        "conversation_scope": (
            "requesting_user_only" if include_conversations else "not_included"
        ),
        "document_count": len(documents),
        "reference_count": len(papers),
        "note_count": len(annotations),
        "conversation_count": len(conversations),
        "latex_workspace_saved": workspace is not None,
        "python_workspace_saved": python_workspace is not None,
        "python_artifact_count": len(python_artifacts),
        "systematic_review_saved": review is not None,
    }
    archive_file = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES, mode="w+b")
    archive_ready = False
    try:
        with zipfile.ZipFile(
            archive_file,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(
                "README.txt",
                (
                    "Fieldnotes project export\n"
                    "=========================\n\n"
                    "project.json contains project metadata. References are provided as "
                    "JSON, RIS, and BibTeX; notes and review details are JSON; writing "
                    "files are plain text. Python source and generated outputs are "
                    "included under writing/python/ and writing/python-output/.\n"
                    "documents/index.json lists project documents. Original files are "
                    "included only when selected in the export options.\n"
                    "When conversations are selected, the archive contains only "
                    "conversations authored by the person who requested this export. "
                    "Other collaborators' conversations remain private.\n"
                    "This archive is a portable export; it is not an automatic restore "
                    "file for Fieldnotes.\n"
                ),
            )
            _write_json(archive, "manifest.json", manifest)
            _write_json(archive, "project.json", project_data)
            _write_json(archive, "documents/index.json", document_index)
            _write_json(archive, "references/references.json", paper_data)
            archive.writestr(
                "references/references.ris",
                format_references(bibtex_references, "ris"),
            )
            archive.writestr(
                "references/references.bib",
                format_references(bibtex_references, "bibtex"),
            )
            _write_json(archive, "notes/annotations.json", annotation_data)
            archive.writestr(
                "writing/main.tex",
                workspace.main_tex if workspace else DEFAULT_MAIN_TEX,
            )
            archive.writestr(
                "writing/references.bib",
                workspace.references_bib if workspace else "",
            )
            if python_workspace is not None:
                python_files = (
                    python_workspace.files
                    if python_workspace.files
                    else [{"filename": "main.py", "code": python_workspace.code}]
                )
                for source in python_files:
                    archive.writestr(
                        f"writing/python/{source['filename']}",
                        source["code"],
                    )
            for artifact in python_artifacts:
                archive.writestr(
                    f"writing/python-output/{artifact.filename}",
                    artifact.content,
                )
            _write_json(
                archive,
                "review/systematic_review.json",
                {
                    "review_question": review.review_question if review else "",
                    "protocol": review.protocol if review else "",
                    "updated_at": (
                        review.updated_at.isoformat()
                        if review and review.updated_at
                        else None
                    ),
                },
            )
            if include_original_documents:
                for document in documents:
                    try:
                        contents = read_document(document.storage_path)
                    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                        raise HTTPException(
                            status_code=502,
                            detail=(
                                "Original project documents could not be read; "
                                "the export was not created."
                            ),
                        ) from exc
                    archive.writestr(
                        (
                            f"original_documents/{document.document_id}/"
                            f"{_safe_document_filename(document.filename)}"
                        ),
                        contents,
                    )
            for conversation in conversations:
                messages = list(
                    db.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation.conversation_id)
                        .order_by(Message.created_at, Message.message_id)
                    ).all()
                )
                detail = _conversation_detail(
                    db,
                    literature_db,
                    conversation,
                    messages,
                )
                safe_messages = [
                    message.model_copy(
                        update={
                            "sources": [
                                source
                                for source in message.sources
                                if (
                                    source.kind == "document"
                                    and source.document_id in project_document_ids
                                )
                                or (
                                    source.kind == "paper"
                                    and source.paper_id in project_paper_ids
                                )
                            ]
                        }
                    )
                    for message in detail.messages
                ]
                _write_json(
                    archive,
                    f"conversations/{conversation.conversation_id}.json",
                    detail.model_copy(update={"messages": safe_messages}).model_dump(
                        mode="json"
                    ),
                )
        archive_file.seek(0)
        archive_ready = True
    finally:
        if not archive_ready:
            archive_file.close()

    return StreamingResponse(
        _stream_archive(archive_file),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="project-backup.zip"',
            "Cache-Control": "no-store",
        },
    )
