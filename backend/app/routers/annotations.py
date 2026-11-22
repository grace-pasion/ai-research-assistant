import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import Annotation, Document, Paper, ProjectPaper, User
from app.schemas import AnnotationCreate, AnnotationResponse, AnnotationUpdate
from app.security import get_current_user, require_project_access

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
    require_project_access(db, project_id, user.user_id)
    document = _require_document(db, project_id, document_id)
    _validate_offsets(payload, document.extracted_text or "")
    annotation = Annotation(
        project_id=project_id,
        document_id=document_id,
        quote=payload.quote,
        note=payload.note,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
    )
    db.add(annotation)
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
    require_project_access(db, project_id, user.user_id)
    paper = _require_saved_paper(db, literature_db, project_id, paper_id)
    _validate_offsets(payload, _plain_abstract(paper.abstract))
    annotation = Annotation(
        project_id=project_id,
        paper_id=paper_id,
        quote=payload.quote,
        note=payload.note,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
    )
    db.add(annotation)
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
):
    require_project_access(db, project_id, user.user_id)
    _require_document(db, project_id, document_id)
    annotation = _get_annotation(db, project_id, annotation_id, document_id=document_id)
    if not payload.note and not annotation.quote:
        raise HTTPException(status_code=422, detail="Add a note or select text to highlight.")
    annotation.note = payload.note
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
    require_project_access(db, project_id, user.user_id)
    _require_saved_paper(db, literature_db, project_id, paper_id)
    annotation = _get_annotation(db, project_id, annotation_id, paper_id=paper_id)
    if not payload.note and not annotation.quote:
        raise HTTPException(status_code=422, detail="Add a note or select text to highlight.")
    annotation.note = payload.note
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
    require_project_access(db, project_id, user.user_id)
    _require_document(db, project_id, document_id)
    annotation = _get_annotation(db, project_id, annotation_id, document_id=document_id)
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
    require_project_access(db, project_id, user.user_id)
    _require_saved_paper(db, literature_db, project_id, paper_id)
    annotation = _get_annotation(db, project_id, annotation_id, paper_id=paper_id)
    db.delete(annotation)
    db.commit()
