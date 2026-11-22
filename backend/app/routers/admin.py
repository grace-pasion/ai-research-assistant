import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    Conversation,
    Document,
    ProjectPaper,
    ResearchProject,
    User,
    UserActivity,
)
from app.schemas import (
    AdminActivityItem,
    AdminActivityPage,
    AdminLoginRequest,
    AdminUserPage,
    AdminUserSummary,
    TokenResponse,
    UserResponse,
)
from app.security import (
    create_access_token,
    get_current_admin,
    verify_password,
)
from app.services.audit import record_activity
from app.services.storage import delete_document as delete_stored_document

router = APIRouter(prefix="/api/admin", tags=["administrator"])


@router.post("/auth/login", response_model=TokenResponse)
def admin_login(payload: AdminLoginRequest, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    user = db.scalar(select(User).where(User.email == email))
    if (
        email.casefold() not in get_settings().admin_email_list
        or user is None
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    record_activity(db, user.user_id, "admin.login")
    db.commit()
    return TokenResponse(access_token=create_access_token(user.user_id), user=user)


@router.get("/me", response_model=UserResponse)
def admin_me(user: User = Depends(get_current_admin)):
    return user


@router.get("/users", response_model=AdminUserPage)
def list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    project_count = (
        select(func.count(ResearchProject.project_id))
        .where(ResearchProject.user_id == User.user_id)
        .correlate(User)
        .scalar_subquery()
    )
    document_count = (
        select(func.count(Document.document_id))
        .join(ResearchProject, ResearchProject.project_id == Document.project_id)
        .where(ResearchProject.user_id == User.user_id)
        .correlate(User)
        .scalar_subquery()
    )
    saved_paper_count = (
        select(func.count(ProjectPaper.paper_id))
        .join(ResearchProject, ResearchProject.project_id == ProjectPaper.project_id)
        .where(ResearchProject.user_id == User.user_id)
        .correlate(User)
        .scalar_subquery()
    )
    conversation_count = (
        select(func.count(Conversation.conversation_id))
        .where(Conversation.user_id == User.user_id)
        .correlate(User)
        .scalar_subquery()
    )
    last_activity = (
        select(func.max(UserActivity.created_at))
        .where(UserActivity.user_id == User.user_id)
        .correlate(User)
        .scalar_subquery()
    )
    rows = db.execute(
        select(
            User,
            project_count.label("project_count"),
            document_count.label("document_count"),
            saved_paper_count.label("saved_paper_count"),
            conversation_count.label("conversation_count"),
            last_activity.label("last_activity_at"),
        )
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(User)) or 0
    return AdminUserPage(
        users=[
            AdminUserSummary(
                user_id=user.user_id,
                email=user.email,
                name=user.name,
                created_at=user.created_at,
                project_count=projects,
                document_count=documents,
                saved_paper_count=saved_papers,
                conversation_count=conversations,
                last_activity_at=last_seen,
            )
            for user, projects, documents, saved_papers, conversations, last_seen in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/activity", response_model=AdminActivityPage)
def list_activity(
    user_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    conditions = [UserActivity.user_id == user_id] if user_id else []
    query = (
        select(UserActivity, User.email)
        .join(User, User.user_id == UserActivity.user_id)
        .where(*conditions)
        .order_by(UserActivity.created_at.desc())
    )
    rows = db.execute(query.offset(offset).limit(limit)).all()
    total_query = select(func.count(UserActivity.activity_id))
    if user_id:
        total_query = total_query.where(UserActivity.user_id == user_id)
    total = db.scalar(total_query) or 0
    return AdminActivityPage(
        events=[
            AdminActivityItem(
                activity_id=event.activity_id,
                user_id=event.user_id,
                email=email,
                action=event.action,
                details=event.details,
                created_at=event.created_at,
            )
            for event, email in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own administrator account.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    document_paths = db.scalars(
        select(Document.storage_path)
        .join(ResearchProject, ResearchProject.project_id == Document.project_id)
        .where(ResearchProject.user_id == user_id)
    ).all()
    for storage_path in document_paths:
        try:
            delete_stored_document(storage_path)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail="User files could not all be removed; the account was not deleted.",
            ) from exc

    project_count = db.scalar(
        select(func.count(ResearchProject.project_id)).where(ResearchProject.user_id == user_id)
    ) or 0
    db.add(
        UserActivity(
            user_id=admin.user_id,
            action="admin.user_deleted",
            details={
                "target_user_id": str(user_id),
                "project_count": project_count,
                "document_count": len(document_paths),
            },
        )
    )
    db.delete(user)
    db.commit()
