import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProjectFileVersion, User

WORKSPACE_HISTORY_LIMIT = 20
WorkspaceType = Literal["latex", "python"]


def latest_file_version(
    db: Session,
    project_id: uuid.UUID,
    workspace_type: WorkspaceType,
    filename: str,
) -> ProjectFileVersion | None:
    return db.scalar(
        select(ProjectFileVersion)
        .where(
            ProjectFileVersion.project_id == project_id,
            ProjectFileVersion.workspace_type == workspace_type,
            ProjectFileVersion.filename == filename,
        )
        .order_by(ProjectFileVersion.version_number.desc())
        .limit(1)
    )


def record_file_version(
    db: Session,
    project_id: uuid.UUID,
    workspace_type: WorkspaceType,
    filename: str,
    content: str,
    created_by: uuid.UUID | None,
    *,
    force: bool = False,
) -> ProjectFileVersion | None:
    latest = latest_file_version(db, project_id, workspace_type, filename)
    if not force and latest is not None and latest.content == content:
        return None

    version = ProjectFileVersion(
        project_id=project_id,
        workspace_type=workspace_type,
        filename=filename,
        version_number=latest.version_number + 1 if latest is not None else 1,
        content=content,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
    )
    db.add(version)
    db.flush()

    expired = db.scalars(
        select(ProjectFileVersion)
        .where(
            ProjectFileVersion.project_id == project_id,
            ProjectFileVersion.workspace_type == workspace_type,
            ProjectFileVersion.filename == filename,
        )
        .order_by(ProjectFileVersion.version_number.desc())
        .offset(WORKSPACE_HISTORY_LIMIT)
    ).all()
    for old_version in expired:
        db.delete(old_version)
    return version


def list_file_versions(
    db: Session,
    project_id: uuid.UUID,
    workspace_type: WorkspaceType,
) -> list[tuple[ProjectFileVersion, str | None]]:
    rows = db.execute(
        select(ProjectFileVersion, User.name)
        .outerjoin(User, User.user_id == ProjectFileVersion.created_by)
        .where(
            ProjectFileVersion.project_id == project_id,
            ProjectFileVersion.workspace_type == workspace_type,
        )
        .order_by(
            ProjectFileVersion.filename,
            ProjectFileVersion.version_number.desc(),
        )
    ).all()
    return [(version, author_name) for version, author_name in rows]


def get_file_version(
    db: Session,
    project_id: uuid.UUID,
    workspace_type: WorkspaceType,
    version_id: uuid.UUID,
) -> tuple[ProjectFileVersion, str | None] | None:
    return db.execute(
        select(ProjectFileVersion, User.name)
        .outerjoin(User, User.user_id == ProjectFileVersion.created_by)
        .where(
            ProjectFileVersion.version_id == version_id,
            ProjectFileVersion.project_id == project_id,
            ProjectFileVersion.workspace_type == workspace_type,
        )
    ).first()
