import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ResearchProject, User
from app.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from app.security import get_current_user, require_project_owner
from app.services.audit import record_activity

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return list(
        db.scalars(
            select(ResearchProject)
            .where(ResearchProject.user_id == user.user_id)
            .order_by(ResearchProject.updated_at.desc())
        ).all()
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = ResearchProject(
        user_id=user.user_id,
        project_name=payload.project_name.strip(),
        description=payload.description.strip(),
    )
    db.add(project)
    record_activity(db, user.user_id, "project.created")
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = require_project_owner(db, project_id, user.user_id)
    project.project_name = payload.project_name.strip()
    project.description = payload.description.strip()
    record_activity(db, user.user_id, "project.updated")
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from pathlib import Path

    from app.config import get_settings
    from app.models import Document
    from app.services.storage import (
        delete_document as delete_stored_document,
        is_remote_storage_path,
    )

    project = require_project_owner(db, project_id, user.user_id)
    document_paths = db.scalars(
        select(Document.storage_path).where(Document.project_id == project_id)
    ).all()
    record_activity(
        db,
        user.user_id,
        "project.deleted",
        {"document_count": len(document_paths)},
    )
    db.delete(project)
    db.commit()
    try:
        for storage_path in document_paths:
            delete_stored_document(storage_path)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Project was deleted, but one or more stored files could not be deleted."
            ),
        ) from exc
    if document_paths and not any(is_remote_storage_path(path) for path in document_paths):
        project_dir = Path(get_settings().storage_dir) / str(project_id)
        if project_dir.is_dir():
            project_dir.rmdir()
