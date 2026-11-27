from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NotificationPreference, User
from app.schemas import (
    NotificationPreferencesResponse,
    NotificationPreferencesUpdate,
)
from app.security import get_current_user

router = APIRouter(tags=["notifications"])


def _preferences_response(
    preferences: NotificationPreference | None,
) -> NotificationPreferencesResponse:
    if preferences is None:
        return NotificationPreferencesResponse(
            project_invitations=True,
            invitation_responses=True,
            direct_messages=True,
            saved_search_alerts=True,
            annotation_mentions=True,
            task_assignments=True,
        )
    return NotificationPreferencesResponse(
        project_invitations=preferences.project_invitations,
        invitation_responses=preferences.invitation_responses,
        direct_messages=preferences.direct_messages,
        saved_search_alerts=preferences.saved_search_alerts,
        annotation_mentions=preferences.annotation_mentions,
        task_assignments=preferences.task_assignments,
    )


@router.get(
    "/api/notifications/preferences",
    response_model=NotificationPreferencesResponse,
)
def get_notification_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _preferences_response(db.get(NotificationPreference, user.user_id))


@router.put(
    "/api/notifications/preferences",
    response_model=NotificationPreferencesResponse,
)
def update_notification_preferences(
    payload: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    preferences = db.get(NotificationPreference, user.user_id)
    values = payload.model_dump()
    if preferences is None:
        preferences = NotificationPreference(user_id=user.user_id, **values)
        db.add(preferences)
    else:
        for field, value in values.items():
            setattr(preferences, field, value)
    db.commit()
    return _preferences_response(preferences)
