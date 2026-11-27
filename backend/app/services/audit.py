import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import ProjectActivity, UserActivity


def record_activity(
    db: Session,
    user_id: uuid.UUID,
    action: str,
    details: dict[str, Any] | None = None,
    *,
    project_id: uuid.UUID | None = None,
) -> None:
    db.add(UserActivity(user_id=user_id, action=action, details=details or {}))
    if project_id is not None:
        db.add(
            ProjectActivity(
                project_id=project_id,
                actor_id=user_id,
                action=action,
            )
        )
