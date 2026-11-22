from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import TeamWorkspaceMembership, User

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("fieldnotes-invalid-login-placeholder")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def verify_password_or_dummy(password: str, hashed_password: str | None) -> bool:
    if hashed_password is None:
        password_hash.verify(password, DUMMY_PASSWORD_HASH)
        return False
    return verify_password(password, hashed_password)


def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
        user_id = UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise unauthorized from None
    user = db.scalar(select(User).where(User.user_id == user_id))
    if user is None:
        raise unauthorized
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.email.casefold() not in get_settings().admin_email_list:
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


def require_project_owner(db: Session, project_id: UUID, user_id: UUID):
    from app.models import ResearchProject

    project = db.scalar(
        select(ResearchProject).where(
            ResearchProject.project_id == project_id,
            ResearchProject.user_id == user_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    return project


def require_project_access(db: Session, project_id: UUID, user_id: UUID):
    from app.models import ProjectInvitation, ResearchProject

    project = db.get(ResearchProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    if project.user_id == user_id:
        return project
    workspace_membership = db.scalar(
        select(TeamWorkspaceMembership.membership_id).where(
            TeamWorkspaceMembership.team_workspace_id == project.team_workspace_id,
            TeamWorkspaceMembership.user_id == user_id,
        )
    ) if project.team_workspace_id is not None else None
    if workspace_membership is not None:
        return project
    invitation = db.scalar(
        select(ProjectInvitation.invitation_id).where(
            ProjectInvitation.project_id == project_id,
            ProjectInvitation.invitee_id == user_id,
            ProjectInvitation.status == "accepted",
        )
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    return project
