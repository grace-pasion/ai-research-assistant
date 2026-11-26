import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import Annotation, Document, Notification, Paper, ProjectPaper, ResearchProject, User
from app.schemas import (
    AnnotationSourceLink,
    AnnotationCreate,
    AnnotationResponse,
    AnnotationUpdate,
    ProjectAnnotationResponse,
)
from app.security import get_current_user, require_project_access
from app.services.project_collaboration import (
    extract_mentioned_usernames,
    list_project_collaborators,
)

router = APIRouter(tags=["annotations"])


def _plain_abstract(value: str | None) -> str:
    return re.sub(r"<[^>]*>", "", value or "")


def _require_document(db: Session, project_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def _require_saved_paper(
    db: Session, literature_db: Session, project_id: uuid.UUID, paper_id: uuid.UUID
) -> Paper:
    if db.get(ProjectPaper, (project_id, paper_id)) is None:
        raise HTTPException(status_code=404, detail="Saved paper not found.")
    paper = literature_db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Saved paper not found.")
    return paper


def _validate_offsets(payload: AnnotationCreate, source_text: str) -> None:
    if payload.start_offset is None:
        return
    if payload.end_offset > len(source_text):
        raise HTTPException(status_code=422, detail="The selected text is outside the source.")
    if source_text[payload.start_offset : payload.end_offset] != payload.quote:
        raise HTTPException(status_code=422, detail="The selected text no longer matches the source.")


def _annotation_query(
    db: Session,
    project_id: uuid.UUID,
    *,
    document_id: uuid.UUID | None = None,
    paper_id: uuid.UUID | None = None,
) -> list[Annotation]:
    return list(
        db.scalars(
            select(Annotation)
            .where(
                Annotation.project_id == project_id,
                Annotation.document_id == document_id,
                Annotation.paper_id == paper_id,
            )
            .order_by(Annotation.created_at, Annotation.annotation_id)
        ).all()
    )


def _get_annotation(
    db: Session,
    project_id: uuid.UUID,
    annotation_id: uuid.UUID,
    *,
    document_id: uuid.UUID | None = None,
    paper_id: uuid.UUID | None = None,
) -> Annotation:
    annotation = db.scalar(
        select(Annotation).where(
            Annotation.annotation_id == annotation_id,
            Annotation.project_id == project_id,
            Annotation.document_id == document_id,
            Annotation.paper_id == paper_id,
        )
    )
    if annotation is None:
        raise HTTPException(status_code=404, detail="Annotation not found.")
    return annotation


def _require_annotation_author(
    db: Session,
    annotation: Annotation,
    user: User,
) -> None:
    if annotation.created_by == user.user_id:
        return
    project = db.get(ResearchProject, annotation.project_id)
    if project is None or project.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Only the comment author or project owner can edit it.")


def _notify_new_mentions(
    db: Session,
    *,
    project_id: uuid.UUID,
    annotation: Annotation,
    note: str,
    previous_note: str,
    source_type: str,
    source_id: uuid.UUID,
    source_title: str,
    actor: User,
) -> None:
    if not extract_mentioned_usernames(note):
        return
    project = db.get(ResearchProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found.")
    collaborators = list_project_collaborators(db, project)
    users_by_username = {
        collaborator.username.casefold(): collaborator
        for collaborator, _ in collaborators
        if collaborator.username
    }
    known_usernames = set(users_by_username)
    mentioned = extract_mentioned_usernames(note, known_usernames)
    if not mentioned:
        return
    newly_mentioned = mentioned - extract_mentioned_usernames(
        previous_note,
        known_usernames,
    )
    unknown = newly_mentioned - users_by_username.keys()
    if unknown:
        names = ", ".join(f"@{username}" for username in sorted(unknown))
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"These mentions are not project collaborators: {names}.",
        )
    for username in sorted(newly_mentioned):
        recipient = users_by_username[username]
        if recipient.user_id == actor.user_id:
            continue
        db.add(
            Notification(
                recipient_id=recipient.user_id,
                actor_id=actor.user_id,
                kind="annotation_mention",
                project_id=project_id,
                details={
                    "annotation_id": str(annotation.annotation_id),
                    "source_type": source_type,
                    "source_id": str(source_id),
                    "source_title": source_title,
                },
            )
        )


def _validate_related_sources(
    db: Session,
    literature_db: Session,
    project_id: uuid.UUID,
    annotation: Annotation,
    related_sources: list[AnnotationSourceLink],
) -> list[dict[str, str]]:
    seen: set[tuple[str, uuid.UUID]] = set()
    validated = []
    for source in related_sources:
        key = (source.source_type, source.source_id)
        if key in seen:
            raise HTTPException(status_code=422, detail="Related sources must be unique.")
        seen.add(key)
        if (
            (source.source_type == "document" and annotation.document_id == source.source_id)
            or (source.source_type == "paper" and annotation.paper_id == source.source_id)
        ):
            raise HTTPException(status_code=422, detail="A note cannot link to its own source.")
        if source.source_type == "document":
            document = db.get(Document, source.source_id)
            if document is None or document.project_id != project_id:
                raise HTTPException(status_code=404, detail="Related document not found in this project.")
        else:
            _require_saved_paper(db, literature_db, project_id, source.source_id)
        validated.append(
            {"source_type": source.source_type, "source_id": str(source.source_id)}
        )
    return validated


@router.get(
    "/api/projects/{project_id}/annotations",
    response_model=list[ProjectAnnotationResponse],
)
def list_project_annotations(
    project_id: uuid.UUID,
    q: Annotated[str, Query(max_length=200)] = "",
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    annotations = db.scalars(
        select(Annotation)
        .where(Annotation.project_id == project_id)
        .order_by(Annotation.updated_at.desc(), Annotation.annotation_id)
    ).all()
    document_ids = {item.document_id for item in annotations if item.document_id is not None}
    paper_ids = {item.paper_id for item in annotations if item.paper_id is not None}
    saved_paper_ids = set(
        db.scalars(
            select(ProjectPaper.paper_id).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.paper_id.in_(paper_ids),
            )
        ).all()
    ) if paper_ids else set()
    paper_ids.intersection_update(saved_paper_ids)
    documents = db.scalars(
        select(Document).where(
            Document.project_id == project_id,
            Document.document_id.in_(document_ids),
        )
    ).all() if document_ids else []
    papers = literature_db.scalars(
        select(Paper).where(Paper.paper_id.in_(paper_ids))
    ).all() if paper_ids else []
    documents_by_id = {document.document_id: document for document in documents}
    papers_by_id = {paper.paper_id: paper for paper in papers}
    search_text = q.strip().casefold()
    results = []
    for annotation in annotations:
        if annotation.document_id is not None:
            source_type = "document"
            source = documents_by_id.get(annotation.document_id)
            if source is None:
                continue
            source_title = source.filename
        else:
            source_type = "paper"
            if annotation.paper_id not in saved_paper_ids:
                continue
            source = papers_by_id.get(annotation.paper_id)
            if source is None:
                continue
            source_title = source.title
        if search_text and search_text not in " ".join(
            (source_title, annotation.quote or "", annotation.note, *annotation.tags)
        ).casefold():
            continue
        results.append(
            ProjectAnnotationResponse(
                **AnnotationResponse.model_validate(annotation).model_dump(),
                source_type=source_type,
                source_title=source_title,
            )
        )
    return results


@router.get(
    "/api/projects/{project_id}/documents/{document_id}/annotations",
    response_model=list[AnnotationResponse],
)
def list_document_annotations(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    _require_document(db, project_id, document_id)
    return _annotation_query(db, project_id, document_id=document_id)


@router.post(
    "/api/projects/{project_id}/documents/{document_id}/annotations",
    response_model=AnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document_annotation(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: AnnotationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "comment")
    document = _require_document(db, project_id, document_id)
    _validate_offsets(payload, document.extracted_text or "")
    annotation = Annotation(
        project_id=project_id,
        document_id=document_id,
        created_by=user.user_id,
        quote=payload.quote,
        note=payload.note,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
    )
    db.add(annotation)
    db.flush()
    _notify_new_mentions(
        db,
        project_id=project_id,
        annotation=annotation,
        note=annotation.note,
        previous_note="",
        source_type="document",
        source_id=document_id,
        source_title=document.filename,
        actor=user,
    )
    db.commit()
    db.refresh(annotation)
    return annotation


@router.get(
    "/api/projects/{project_id}/papers/{paper_id}/annotations",
    response_model=list[AnnotationResponse],
)
def list_paper_annotations(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    _require_saved_paper(db, literature_db, project_id, paper_id)
    return _annotation_query(db, project_id, paper_id=paper_id)


@router.post(
    "/api/projects/{project_id}/papers/{paper_id}/annotations",
    response_model=AnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_paper_annotation(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    payload: AnnotationCreate,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "comment")
    paper = _require_saved_paper(db, literature_db, project_id, paper_id)
    _validate_offsets(payload, _plain_abstract(paper.abstract))
    annotation = Annotation(
        project_id=project_id,
        paper_id=paper_id,
        created_by=user.user_id,
        quote=payload.quote,
        note=payload.note,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
    )
    db.add(annotation)
    db.flush()
    _notify_new_mentions(
        db,
        project_id=project_id,
        annotation=annotation,
        note=annotation.note,
        previous_note="",
        source_type="paper",
        source_id=paper_id,
        source_title=paper.title,
        actor=user,
    )
    db.commit()
    db.refresh(annotation)
    return annotation


@router.patch(
    "/api/projects/{project_id}/documents/{document_id}/annotations/{annotation_id}",
    response_model=AnnotationResponse,
)
def update_document_annotation(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    annotation_id: uuid.UUID,
    payload: AnnotationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    literature_db: Session = Depends(get_literature_db),
):
    require_project_access(db, project_id, user.user_id, "comment")
    document = _require_document(db, project_id, document_id)
    annotation = _get_annotation(db, project_id, annotation_id, document_id=document_id)
    _require_annotation_author(db, annotation, user)
    if payload.note is not None and not payload.note and not annotation.quote:
        raise HTTPException(status_code=422, detail="Add a note or select text to highlight.")
    previous_note = annotation.note
    if payload.note is not None:
        annotation.note = payload.note
    if payload.tags is not None:
        annotation.tags = payload.tags
    if payload.is_pinned is not None:
        annotation.is_pinned = payload.is_pinned
    if payload.related_sources is not None:
        annotation.related_sources = _validate_related_sources(
            db, literature_db, project_id, annotation, payload.related_sources
        )
    if payload.note is not None:
        _notify_new_mentions(
            db,
            project_id=project_id,
            annotation=annotation,
            note=annotation.note,
            previous_note=previous_note,
            source_type="document",
            source_id=document_id,
            source_title=document.filename,
            actor=user,
        )
    db.commit()
    db.refresh(annotation)
    return annotation


@router.patch(
    "/api/projects/{project_id}/papers/{paper_id}/annotations/{annotation_id}",
    response_model=AnnotationResponse,
)
def update_paper_annotation(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    annotation_id: uuid.UUID,
    payload: AnnotationUpdate,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "comment")
    paper = _require_saved_paper(db, literature_db, project_id, paper_id)
    annotation = _get_annotation(db, project_id, annotation_id, paper_id=paper_id)
    _require_annotation_author(db, annotation, user)
    if payload.note is not None and not payload.note and not annotation.quote:
        raise HTTPException(status_code=422, detail="Add a note or select text to highlight.")
    previous_note = annotation.note
    if payload.note is not None:
        annotation.note = payload.note
    if payload.tags is not None:
        annotation.tags = payload.tags
    if payload.is_pinned is not None:
        annotation.is_pinned = payload.is_pinned
    if payload.related_sources is not None:
        annotation.related_sources = _validate_related_sources(
            db, literature_db, project_id, annotation, payload.related_sources
        )
    if payload.note is not None:
        _notify_new_mentions(
            db,
            project_id=project_id,
            annotation=annotation,
            note=annotation.note,
            previous_note=previous_note,
            source_type="paper",
            source_id=paper_id,
            source_title=paper.title,
            actor=user,
        )
    db.commit()
    db.refresh(annotation)
    return annotation


@router.delete(
    "/api/projects/{project_id}/documents/{document_id}/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document_annotation(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    annotation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "comment")
    _require_document(db, project_id, document_id)
    annotation = _get_annotation(db, project_id, annotation_id, document_id=document_id)
    _require_annotation_author(db, annotation, user)
    db.delete(annotation)
    db.commit()


@router.delete(
    "/api/projects/{project_id}/papers/{paper_id}/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_paper_annotation(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    annotation_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "comment")
    _require_saved_paper(db, literature_db, project_id, paper_id)
    annotation = _get_annotation(db, project_id, annotation_id, paper_id=paper_id)
    _require_annotation_author(db, annotation, user)
    db.delete(annotation)
    db.commit()
