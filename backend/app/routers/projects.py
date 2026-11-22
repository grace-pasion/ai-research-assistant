import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ResearchProject, User
from app.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from app.security import get_current_user, require_project_owner

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
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.config import get_settings
    from app.models import Document
    from pathlib import Path

    project = require_project_owner(db, project_id, user.user_id)
    document_paths = db.scalars(
        select(Document.storage_path).where(Document.project_id == project_id)
    ).all()
    db.delete(project)
    db.commit()
    for storage_path in document_paths:
        path = Path(storage_path)
        if path.is_file():
            path.unlink()
    project_dir = Path(get_settings().storage_dir) / str(project_id)
    if project_dir.is_dir():
        project_dir.rmdir()
