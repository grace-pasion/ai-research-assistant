import json
import tempfile
import uuid
import zipfile
import base64
from datetime import datetime, timezone
from typing import Iterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Conversation,
    Document,
    LatexWorkspace,
    Message,
    MessageChunkSource,
    MessagePaperSource,
    PythonAnalysisRun,
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
from app.schemas import ResearchPacketAssistantOutputOption, ResearchPacketRequest
from app.security import get_current_user, require_project_access
from app.services.bibliography import Reference, format_references
from app.services.research_brief import citation_indices
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


def _isoformat_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _stream_archive(archive_file) -> Iterator[bytes]:
    try:
        while chunk := archive_file.read(STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        archive_file.close()


@router.get(
    "/api/projects/{project_id}/research-packet/assistant-outputs",
    response_model=list[ResearchPacketAssistantOutputOption],
)
def list_research_packet_assistant_outputs(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    rows = db.execute(
        select(Message, Conversation)
        .join(Conversation, Conversation.conversation_id == Message.conversation_id)
        .where(
            Conversation.project_id == project_id,
            Conversation.user_id == user.user_id,
            Message.role == "assistant",
            Message.reviewed.is_(True),
            Message.approval_id.is_not(None),
        )
        .order_by(Message.created_at.desc(), Message.message_id)
    ).all()
    return [
        ResearchPacketAssistantOutputOption(
            message_id=message.message_id,
            conversation_id=conversation.conversation_id,
            conversation_title=conversation.title,
            created_at=message.created_at,
            excerpt=" ".join(message.content.split())[:240],
        )
        for message, conversation in rows
    ]


@router.post("/api/projects/{project_id}/research-packet")
def export_research_packet(
    project_id: uuid.UUID,
    payload: ResearchPacketRequest,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    project = require_project_access(db, project_id, user.user_id)
    documents = list(
        db.scalars(
            select(Document).where(Document.project_id == project_id)
        ).all()
    )
    documents_by_id = {document.document_id: document for document in documents}
    papers = list_saved_papers(project_id, db, literature_db, user)
    papers_by_id = {paper.paper_id: paper for paper in papers}
    requested_paper_ids = set(payload.paper_ids)
    if requested_paper_ids - papers_by_id.keys():
        raise HTTPException(
            status_code=404,
            detail="One or more selected papers are not saved in this project.",
        )

    annotations = list_project_annotations(project_id, "", db, literature_db, user)
    annotations_by_id = {annotation.annotation_id: annotation for annotation in annotations}
    requested_annotation_ids = set(payload.annotation_ids)
    if requested_annotation_ids - annotations_by_id.keys():
        raise HTTPException(
            status_code=404,
            detail="One or more selected notes are not available in this project.",
        )

    selected_messages: list[Message] = []
    conversations_by_id: dict[uuid.UUID, Conversation] = {}
    if payload.assistant_message_ids:
        rows = db.execute(
            select(Message, Conversation)
            .join(Conversation, Conversation.conversation_id == Message.conversation_id)
            .where(
                Message.message_id.in_(payload.assistant_message_ids),
                Message.role == "assistant",
                Message.reviewed.is_(True),
                Message.approval_id.is_not(None),
                Conversation.project_id == project_id,
                Conversation.user_id == user.user_id,
            )
        ).all()
        if len(rows) != len(payload.assistant_message_ids):
            raise HTTPException(
                status_code=404,
                detail="One or more selected approved assistant outputs are unavailable.",
            )
        selected_messages = [message for message, _ in rows]
        conversations_by_id = {
            conversation.conversation_id: conversation
            for _, conversation in rows
        }

    note_records = []
    packet_paper_ids = set(requested_paper_ids)
    for annotation_id in payload.annotation_ids:
        annotation = annotations_by_id[annotation_id]
        source_id = annotation.document_id or annotation.paper_id
        related_sources = []
        for link in annotation.related_sources:
            title = None
            if link.source_type == "document" and link.source_id in documents_by_id:
                title = documents_by_id[link.source_id].filename
            elif link.source_type == "paper" and link.source_id in papers_by_id:
                title = papers_by_id[link.source_id].title
            related_sources.append(
                {
                    "source_type": link.source_type,
                    "source_id": str(link.source_id),
                    "title": title,
                }
            )
        note_records.append(
            {
                "annotation_id": str(annotation.annotation_id),
                "source_type": annotation.source_type,
                "source_id": str(source_id),
                "source_title": annotation.source_title,
                "quote": annotation.quote,
                "note": annotation.note,
                "tags": annotation.tags,
                "is_pinned": annotation.is_pinned,
                "related_sources": related_sources,
                "author_name": annotation.author_name,
                "created_at": _isoformat_utc(annotation.created_at),
                "updated_at": _isoformat_utc(annotation.updated_at),
            }
        )
        if annotation.paper_id is not None:
            if annotation.paper_id not in papers_by_id:
                raise HTTPException(
                    status_code=409,
                    detail="A selected note's saved paper is no longer available.",
                )
            packet_paper_ids.add(annotation.paper_id)
        for link in annotation.related_sources:
            if link.source_type == "paper" and link.source_id in papers_by_id:
                packet_paper_ids.add(link.source_id)

    assistant_outputs = []
    for conversation_id in sorted(conversations_by_id, key=str):
        conversation = conversations_by_id[conversation_id]
        conversation_messages = [
            message
            for message in selected_messages
            if message.conversation_id == conversation_id
        ]
        detail = _conversation_detail(
            db,
            literature_db,
            conversation,
            conversation_messages,
        )
        message_details = {message.message_id: message for message in detail.messages}
        for message in sorted(
            conversation_messages,
            key=lambda item: (item.created_at, str(item.message_id)),
        ):
            message_detail = message_details[message.message_id]
            linked_source_count = (
                db.scalar(
                    select(func.count())
                    .select_from(MessageChunkSource)
                    .where(MessageChunkSource.message_id == message.message_id)
                )
                or 0
            ) + (
                db.scalar(
                    select(func.count())
                    .select_from(MessagePaperSource)
                    .where(MessagePaperSource.message_id == message.message_id)
                )
                or 0
            )
            if linked_source_count != len(message_detail.sources):
                raise HTTPException(
                    status_code=409,
                    detail="A selected assistant output cites a source that is no longer available.",
                )
            citation_records = []
            for index, source in enumerate(message_detail.sources, start=1):
                if source.kind == "document":
                    if source.document_id not in documents_by_id:
                        raise HTTPException(
                            status_code=409,
                            detail="A selected assistant output cites a document no longer available in this project.",
                        )
                    document = documents_by_id[source.document_id]
                    citation_records.append(
                        {
                            "citation": f"[S{index}]",
                            "source_type": "document",
                            "source_id": str(source.source_id),
                            "document_id": str(document.document_id),
                            "title": document.filename,
                            "page_number": source.page_number,
                            "excerpt": source.excerpt,
                        }
                    )
                else:
                    if source.paper_id not in papers_by_id:
                        raise HTTPException(
                            status_code=409,
                            detail="A selected assistant output cites a paper no longer saved in this project.",
                        )
                    paper = papers_by_id[source.paper_id]
                    packet_paper_ids.add(paper.paper_id)
                    citation_records.append(
                        {
                            "citation": f"[S{index}]",
                            "source_type": "paper",
                            "source_id": str(source.paper_id),
                            "title": paper.title,
                            "authors": [author.author_name for author in paper.authors],
                            "year": paper.publication_year,
                            "doi": paper.doi,
                            "url": paper.paper_url,
                            "excerpt": source.excerpt,
                        }
                    )
            if any(
                index < 1 or index > len(citation_records)
                for index in citation_indices(message.content)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="A selected assistant output has citations to unavailable sources.",
                )
            question = db.scalar(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role == "user",
                    Message.created_at < message.created_at,
                )
                .order_by(Message.created_at.desc(), Message.message_id.desc())
                .limit(1)
            )
            assistant_outputs.append(
                {
                    "message_id": str(message.message_id),
                    "conversation_id": str(conversation_id),
                    "conversation_title": conversation.title,
                    "created_at": _isoformat_utc(message.created_at),
                    "approved": True,
                    "question": question.content if question else None,
                    "answer": message.content,
                    "citations": citation_records,
                }
            )

    packet_papers = [papers_by_id[paper_id] for paper_id in packet_paper_ids]
    paper_records = [
        {
            "paper_id": str(paper.paper_id),
            "title": paper.title,
            "authors": [author.author_name for author in paper.authors],
            "year": paper.publication_year,
            "doi": paper.doi,
            "venue": paper.venue,
            "url": paper.paper_url,
            "abstract": paper.abstract,
            "tags": paper.tags,
        }
        for paper in packet_papers
    ]
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
        for paper in packet_papers
    ]

    manifest = {
        "format": "fieldnotes-research-packet",
        "format_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project_id": str(project.project_id),
        "project_name": project.project_name,
        "exported_by": str(user.user_id),
        "paper_count": len(paper_records),
        "note_count": len(note_records),
        "approved_output_count": len(assistant_outputs),
        "citation_count": sum(len(output["citations"]) for output in assistant_outputs),
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
                    "Fieldnotes research packet\n"
                    "==========================\n\n"
                    "This selected packet contains saved paper metadata, project notes, "
                    "and approved assistant outputs with their source citations. Paper "
                    "references are provided as JSON, RIS, and BibTeX. Assistant outputs "
                    "are authored by the requesting user; other collaborators' private "
                    "conversation histories are not included.\n"
                ),
            )
            _write_json(archive, "manifest.json", manifest)
            _write_json(archive, "papers/papers.json", paper_records)
            _write_json(archive, "papers/notes.json", note_records)
            _write_json(archive, "assistant/approved-outputs.json", assistant_outputs)
            archive.writestr("references/references.ris", format_references(references, "ris"))
            archive.writestr("references/references.bib", format_references(references, "bibtex"))
            for output in assistant_outputs:
                question_text = output["question"] or "Question unavailable"
                citation_lines = []
                for citation in output["citations"]:
                    detail = ""
                    if citation["source_type"] == "document" and citation["page_number"]:
                        detail = f" (PDF page {citation['page_number']})"
                    elif citation.get("doi"):
                        detail = f" — DOI: {citation['doi']}"
                    citation_lines.append(
                        f"- {citation['citation']} {citation['title']}{detail}"
                    )
                archive.writestr(
                    f"assistant/approved-outputs/{output['message_id']}.md",
                    (
                        f"# {output['conversation_title']}\n\n"
                        f"**Prepared:** {output['created_at']}\n\n"
                        f"## Question\n\n{question_text}\n\n"
                        f"## Approved response\n\n{output['answer']}\n\n"
                        f"## Citations\n\n"
                        + "\n".join(citation_lines)
                        + "\n"
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
            "Content-Disposition": 'attachment; filename="research-packet.zip"',
            "Cache-Control": "no-store",
        },
    )

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
    run_ids = {artifact.run_id for artifact in python_artifacts if artifact.run_id is not None}
    python_runs = (
        list(
            db.scalars(
                select(PythonAnalysisRun)
                .where(PythonAnalysisRun.project_id == project_id)
                .where(PythonAnalysisRun.run_id.in_(run_ids))
                .order_by(PythonAnalysisRun.run_at, PythonAnalysisRun.run_id)
            ).all()
        )
        if run_ids
        else []
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
        "format_version": 2,
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
        "python_run_count": len(python_runs),
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
                    "included under writing/python/ and writing/python-output/. Reproducible "
                    "run snapshots are included under writing/python-runs/.\n"
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
                "writing/python-output/manifest.json",
                [
                    {
                        "filename": artifact.filename,
                        "run_id": str(artifact.run_id) if artifact.run_id else None,
                        "run_at": _isoformat_utc(artifact.run_at) if artifact.run_at else None,
                        "script_filename": artifact.script_filename,
                        "input_filenames": artifact.input_filenames,
                    }
                    for artifact in python_artifacts
                ],
            )
            for run in python_runs:
                run_root = f"writing/python-runs/{run.run_id}"
                _write_json(
                    archive,
                    f"{run_root}/provenance.json",
                    {
                        "run_id": str(run.run_id),
                        "run_at": _isoformat_utc(run.run_at),
                        "script_filename": run.script_filename,
                        "source_files": [
                            {
                                "filename": source["filename"],
                                "path": f"{run_root}/source/{source['filename']}",
                            }
                            for source in run.source_files
                        ],
                        "inputs": [
                            {
                                "filename": str(input_file["filename"]),
                                "byte_size": int(input_file["byte_size"]),
                                "path": f"{run_root}/inputs/{input_file['filename']}",
                            }
                            for input_file in run.input_files
                        ],
                    },
                )
                for source in run.source_files:
                    archive.writestr(
                        f"{run_root}/source/{source['filename']}",
                        source["code"],
                    )
                for input_file in run.input_files:
                    archive.writestr(
                        f"{run_root}/inputs/{input_file['filename']}",
                        base64.b64decode(str(input_file["content_base64"]), validate=True),
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
