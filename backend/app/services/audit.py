import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import UserActivity


def record_activity(
    db: Session,
    user_id: uuid.UUID,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(UserActivity(user_id=user_id, action=action, details=details or {}))
