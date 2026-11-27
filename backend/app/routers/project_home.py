import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ProjectActivity, User
from app.schemas import ProjectActivityResponse
from app.security import get_current_user, require_project_access

router = APIRouter(tags=["project home"])
RECENT_ACTIVITY_LIMIT = 12


@router.get(
    "/api/projects/{project_id}/home/activity",
    response_model=list[ProjectActivityResponse],
)
def list_project_home_activity(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    rows = db.execute(
        select(ProjectActivity, User.name)
        .outerjoin(User, ProjectActivity.actor_id == User.user_id)
        .where(ProjectActivity.project_id == project_id)
        .order_by(ProjectActivity.created_at.desc(), ProjectActivity.activity_id)
        .limit(RECENT_ACTIVITY_LIMIT)
    ).all()
    return [
        ProjectActivityResponse(
            activity_id=activity.activity_id,
            action=activity.action,
            actor_name=actor_name,
            created_at=activity.created_at,
        )
        for activity, actor_name in rows
    ]
