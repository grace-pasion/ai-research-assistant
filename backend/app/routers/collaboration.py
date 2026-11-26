import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    DirectMessage,
    Notification,
    ProjectInvitation,
    ResearchProject,
    User,
)
from app.schemas import (
    ColleagueResponse,
    DirectMessageCreate,
    DirectMessageResponse,
    InvitationResponseRequest,
    MessageThreadResponse,
    NotificationResponse,
    ProjectCollaboratorResponse,
    ProjectInvitationCreate,
    ProjectInvitationResponse,
    ProjectInvitationRoleUpdate,
)
from app.security import get_current_user, require_project_access, require_project_owner
from app.services.audit import record_activity
from app.services.project_collaboration import list_project_collaborators

router = APIRouter(tags=["collaboration"])


def _invitation_response(invitation: ProjectInvitation, invitee: User) -> dict:
    return {
        "invitation_id": invitation.invitation_id,
        "project_id": invitation.project_id,
        "inviter_id": invitation.inviter_id,
        "invitee_id": invitation.invitee_id,
        "status": invitation.status,
        "role": invitation.role,
        "created_at": invitation.created_at,
        "updated_at": invitation.updated_at,
        "invitee_name": invitee.name,
        "invitee_username": invitee.username or "",
        "invitee_email": invitee.email,
    }


@router.get(
    "/api/projects/{project_id}/collaborators",
    response_model=list[ProjectCollaboratorResponse],
)
def list_collaborators(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = require_project_access(db, project_id, user.user_id)
    return [
        {
            "user_id": collaborator.user_id,
            "username": collaborator.username or "",
            "name": collaborator.name,
            "role": role,
        }
        for collaborator, role in list_project_collaborators(db, project)
    ]


@router.post(
    "/api/projects/{project_id}/invitations",
    response_model=ProjectInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_to_project(
    project_id: uuid.UUID,
    payload: ProjectInvitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    identifier = payload.identifier.strip().casefold()
    lookup_identifier = (
        identifier[1:]
        if identifier.startswith("@") and identifier.count("@") == 1
        else identifier
    )
    invitee = db.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == lookup_identifier,
                func.lower(User.username) == lookup_identifier,
            )
        )
    )
    if invitee is None:
        raise HTTPException(
            status_code=404,
            detail="No registered account matches that username or email address.",
        )
    if invitee.user_id == user.user_id:
        raise HTTPException(status_code=422, detail="You already own this project.")

    invitation = db.scalar(
        select(ProjectInvitation).where(
            ProjectInvitation.project_id == project_id,
            ProjectInvitation.invitee_id == invitee.user_id,
        )
    )
    if invitation is not None and invitation.status != "declined":
        raise HTTPException(status_code=409, detail="This user already has an invitation or access.")
    now = datetime.now(timezone.utc)
    if invitation is None:
        invitation = ProjectInvitation(
            project_id=project_id,
            inviter_id=user.user_id,
            invitee_id=invitee.user_id,
            status="pending",
            role=payload.role,
        )
        db.add(invitation)
        db.flush()
    else:
        invitation.inviter_id = user.user_id
        invitation.status = "pending"
        invitation.role = payload.role
        invitation.created_at = now
        invitation.updated_at = now
        db.execute(
            update(Notification)
            .where(
                Notification.invitation_id == invitation.invitation_id,
                Notification.recipient_id == invitee.user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=now)
        )

    db.add(
        Notification(
            recipient_id=invitee.user_id,
            actor_id=user.user_id,
            kind="project_invitation",
            project_id=project_id,
            invitation_id=invitation.invitation_id,
        )
    )
    record_activity(db, user.user_id, "project.invited")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This user already has an invitation or access.",
        ) from None
    db.refresh(invitation)
    return _invitation_response(invitation, invitee)


@router.get(
    "/api/projects/{project_id}/invitations",
    response_model=list[ProjectInvitationResponse],
)
def list_project_invitations(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    rows = db.execute(
        select(ProjectInvitation, User)
        .join(User, User.user_id == ProjectInvitation.invitee_id)
        .where(ProjectInvitation.project_id == project_id)
        .order_by(ProjectInvitation.created_at.desc())
    ).all()
    return [_invitation_response(invitation, invitee) for invitation, invitee in rows]


@router.delete(
    "/api/projects/{project_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_project_invitation(
    project_id: uuid.UUID,
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    invitation = db.scalar(
        select(ProjectInvitation).where(
            ProjectInvitation.project_id == project_id,
            ProjectInvitation.invitation_id == invitation_id,
        )
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Project invitation not found.")
    db.delete(invitation)
    db.commit()


@router.patch(
    "/api/projects/{project_id}/invitations/{invitation_id}",
    response_model=ProjectInvitationResponse,
)
def update_project_invitation_role(
    project_id: uuid.UUID,
    invitation_id: uuid.UUID,
    payload: ProjectInvitationRoleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    invitation = db.scalar(
        select(ProjectInvitation).where(
            ProjectInvitation.project_id == project_id,
            ProjectInvitation.invitation_id == invitation_id,
        )
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Project invitation not found.")
    invitation.role = payload.role
    invitation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invitation)
    invitee = db.get(User, invitation.invitee_id)
    if invitee is None:
        raise HTTPException(status_code=404, detail="Project collaborator not found.")
    return _invitation_response(invitation, invitee)


@router.get("/api/invitations", response_model=list[ProjectInvitationResponse])
def list_received_invitations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(ProjectInvitation, User)
        .join(User, User.user_id == ProjectInvitation.invitee_id)
        .where(
            ProjectInvitation.invitee_id == user.user_id,
            ProjectInvitation.status == "pending",
        )
        .order_by(ProjectInvitation.created_at.desc())
    ).all()
    return [_invitation_response(invitation, invitee) for invitation, invitee in rows]


@router.post(
    "/api/invitations/{invitation_id}/respond",
    response_model=ProjectInvitationResponse,
)
def respond_to_invitation(
    invitation_id: uuid.UUID,
    payload: InvitationResponseRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    invitation = db.get(ProjectInvitation, invitation_id)
    if invitation is None or invitation.invitee_id != user.user_id:
        raise HTTPException(status_code=404, detail="Project invitation not found.")
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(ProjectInvitation)
        .where(
            ProjectInvitation.invitation_id == invitation_id,
            ProjectInvitation.invitee_id == user.user_id,
            ProjectInvitation.status == "pending",
        )
        .values(status=payload.response, updated_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        current = db.scalar(
            select(ProjectInvitation).where(
                ProjectInvitation.invitation_id == invitation_id,
                ProjectInvitation.invitee_id == user.user_id,
            )
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Project invitation not found.")
        raise HTTPException(status_code=409, detail="This invitation has already been answered.")
    db.refresh(invitation)
    db.execute(
        update(Notification)
        .where(
            Notification.invitation_id == invitation_id,
            Notification.recipient_id == user.user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.add(
        Notification(
            recipient_id=invitation.inviter_id,
            actor_id=user.user_id,
            kind="invitation_response",
            project_id=invitation.project_id,
            invitation_id=invitation.invitation_id,
        )
    )
    record_activity(db, user.user_id, f"project.invitation_{payload.response}")
    db.commit()
    db.refresh(invitation)
    return _invitation_response(invitation, user)


@router.get("/api/inbox", response_model=list[NotificationResponse])
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(
            Notification,
            User.name,
            User.username,
            User.email,
            ResearchProject.project_name,
            ProjectInvitation.status,
            ProjectInvitation.role,
        )
        .join(User, User.user_id == Notification.actor_id)
        .outerjoin(ResearchProject, ResearchProject.project_id == Notification.project_id)
        .outerjoin(
            ProjectInvitation,
            ProjectInvitation.invitation_id == Notification.invitation_id,
        )
        .where(Notification.recipient_id == user.user_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    ).all()
    return [
        {
            "notification_id": notification.notification_id,
            "kind": notification.kind,
            "actor_id": notification.actor_id,
            "actor_name": actor_name,
            "actor_username": actor_username,
            "actor_email": actor_email,
            "project_id": notification.project_id,
            "project_name": project_name,
            "invitation_id": notification.invitation_id,
            "invitation_status": invitation_status,
            "invitation_role": invitation_role,
            "message_id": notification.message_id,
            "details": notification.details,
            "created_at": notification.created_at,
            "read_at": notification.read_at,
        }
        for (
            notification,
            actor_name,
            actor_username,
            actor_email,
            project_name,
            invitation_status,
            invitation_role,
        ) in rows
    ]


@router.patch("/api/inbox/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notification_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notification = db.scalar(
        select(Notification).where(
            Notification.notification_id == notification_id,
            Notification.recipient_id == user.user_id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()


@router.get("/api/users/search", response_model=list[ColleagueResponse])
def search_colleagues(
    q: str = Query(min_length=2, max_length=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = q.strip().casefold()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search text must be at least 2 characters.")
    pattern = f"%{query}%"
    users = db.scalars(
        select(User)
        .where(
            User.user_id != user.user_id,
            or_(
                func.lower(User.username).like(pattern),
                func.lower(User.email).like(pattern),
                func.lower(User.name).like(pattern),
            ),
        )
        .order_by(User.username)
        .limit(10)
    ).all()
    return [
        {
            "user_id": colleague.user_id,
            "username": colleague.username or "",
            "name": colleague.name,
            "email": colleague.email,
        }
        for colleague in users
    ]


@router.get("/api/messages/threads", response_model=list[MessageThreadResponse])
def list_message_threads(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    other_user_id = case(
        (DirectMessage.sender_id == user.user_id, DirectMessage.recipient_id),
        else_=DirectMessage.sender_id,
    )
    other_ids = db.scalars(
        select(other_user_id)
        .where(
            or_(
                DirectMessage.sender_id == user.user_id,
                DirectMessage.recipient_id == user.user_id,
            )
        )
        .group_by(other_user_id)
        .order_by(func.max(DirectMessage.created_at).desc())
        .limit(30)
    ).all()
    threads = []
    for other_id in other_ids:
        colleague = db.get(User, other_id)
        latest = db.scalar(
            select(DirectMessage)
            .where(
                or_(
                    (DirectMessage.sender_id == user.user_id)
                    & (DirectMessage.recipient_id == other_id),
                    (DirectMessage.sender_id == other_id)
                    & (DirectMessage.recipient_id == user.user_id),
                )
            )
            .order_by(DirectMessage.created_at.desc())
            .limit(1)
        )
        if colleague is None or latest is None:
            continue
        unread_count = db.scalar(
            select(func.count(DirectMessage.message_id)).where(
                DirectMessage.sender_id == other_id,
                DirectMessage.recipient_id == user.user_id,
                DirectMessage.read_at.is_(None),
            )
        ) or 0
        threads.append(
            {
                "user": {
                    "user_id": colleague.user_id,
                    "username": colleague.username or "",
                    "name": colleague.name,
                    "email": colleague.email,
                },
                "last_message": latest.content,
                "updated_at": latest.created_at,
                "unread_count": unread_count,
            }
        )
    return threads


@router.get("/api/messages/{other_user_id}", response_model=list[DirectMessageResponse])
def get_message_thread(
    other_user_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if other_user_id == user.user_id or db.get(User, other_user_id) is None:
        raise HTTPException(status_code=404, detail="Colleague not found.")
    now = datetime.now(timezone.utc)
    incoming = (
        (DirectMessage.sender_id == other_user_id)
        & (DirectMessage.recipient_id == user.user_id)
    )
    outgoing = (
        (DirectMessage.sender_id == user.user_id)
        & (DirectMessage.recipient_id == other_user_id)
    )
    db.execute(
        update(DirectMessage)
        .where(incoming, DirectMessage.read_at.is_(None))
        .values(read_at=now)
    )
    db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user.user_id,
            Notification.actor_id == other_user_id,
            Notification.kind == "message",
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    messages = db.scalars(
        select(DirectMessage)
        .where(or_(incoming, outgoing))
        .order_by(DirectMessage.created_at.desc())
        .limit(100)
    ).all()
    db.commit()
    return list(reversed(messages))


@router.post(
    "/api/messages/{other_user_id}",
    response_model=DirectMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def send_direct_message(
    other_user_id: uuid.UUID,
    payload: DirectMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if other_user_id == user.user_id or db.get(User, other_user_id) is None:
        raise HTTPException(status_code=404, detail="Colleague not found.")
    message = DirectMessage(
        sender_id=user.user_id,
        recipient_id=other_user_id,
        content=payload.content,
    )
    db.add(message)
    db.flush()
    db.add(
        Notification(
            recipient_id=other_user_id,
            actor_id=user.user_id,
            kind="message",
            message_id=message.message_id,
        )
    )
    record_activity(db, user.user_id, "message.sent")
    db.commit()
    db.refresh(message)
    return message


@router.get("/api/inbox/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = db.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.recipient_id == user.user_id,
            Notification.read_at.is_(None),
        )
    ) or 0
    return {"count": count}
