import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    ProjectInvitation,
    ResearchProject,
    TeamWorkspaceMembership,
    User,
)
from app.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from app.security import get_current_user, require_project_owner
from app.services.audit import record_activity

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _project_response(db: Session, project: ResearchProject, user: User) -> ProjectResponse:
    if project.user_id == user.user_id:
        access_role = "owner"
    elif project.team_workspace_id is not None and db.scalar(
        select(TeamWorkspaceMembership.membership_id).where(
            TeamWorkspaceMembership.team_workspace_id == project.team_workspace_id,
            TeamWorkspaceMembership.user_id == user.user_id,
        )
    ):
        access_role = "edit"
    else:
        access_role = db.scalar(
            select(ProjectInvitation.role).where(
                ProjectInvitation.project_id == project.project_id,
                ProjectInvitation.invitee_id == user.user_id,
                ProjectInvitation.status == "accepted",
            )
        ) or "read"
    return ProjectResponse.model_validate(project).model_copy(
        update={"access_role": access_role}
    )


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    projects = list(
        db.scalars(
            select(ResearchProject)
            .where(
                or_(
                    ResearchProject.user_id == user.user_id,
                    ResearchProject.team_workspace_id.in_(
                        select(TeamWorkspaceMembership.team_workspace_id).where(
                            TeamWorkspaceMembership.user_id == user.user_id
                        )
                    ),
                    ResearchProject.project_id.in_(
                        select(ProjectInvitation.project_id).where(
                            ProjectInvitation.invitee_id == user.user_id,
                            ProjectInvitation.status == "accepted",
                        )
                    ),
                )
            )
            .order_by(ResearchProject.updated_at.desc())
        ).all()
    )
    return [_project_response(db, project, user) for project in projects]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.team_workspace_id is not None:
        membership = db.scalar(
            select(TeamWorkspaceMembership.membership_id).where(
                TeamWorkspaceMembership.team_workspace_id == payload.team_workspace_id,
                TeamWorkspaceMembership.user_id == user.user_id,
            )
        )
        if membership is None:
            raise HTTPException(status_code=404, detail="Team workspace not found.")
    project = ResearchProject(
        user_id=user.user_id,
        team_workspace_id=payload.team_workspace_id,
        project_name=payload.project_name.strip(),
        description=payload.description.strip(),
    )
    db.add(project)
    db.flush()
    record_activity(db, user.user_id, "project.created", project_id=project.project_id)
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
    record_activity(db, user.user_id, "project.updated", project_id=project_id)
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
