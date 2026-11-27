from sqlalchemy.orm import Session

from app.models import Notification, NotificationPreference


def _is_enabled(preferences: NotificationPreference | None, kind: str) -> bool:
    if kind == "project_invitation":
        return preferences is None or preferences.project_invitations
    if kind == "invitation_response":
        return preferences is None or preferences.invitation_responses
    if kind == "message":
        return preferences is None or preferences.direct_messages
    if kind == "saved_search_alert":
        return preferences is None or preferences.saved_search_alerts
    if kind == "annotation_mention":
        return preferences is None or preferences.annotation_mentions
    if kind == "task_assigned":
        return preferences is None or preferences.task_assignments
    raise ValueError(f"Unsupported notification kind: {kind}")


def add_notification_if_enabled(db: Session, notification: Notification) -> bool:
    preferences = db.get(NotificationPreference, notification.recipient_id)
    if not _is_enabled(preferences, notification.kind):
        return False
    db.add(notification)
    return True
