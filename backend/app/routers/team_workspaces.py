import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models import (
    ProjectInvitation,
    ResearchProject,
    TeamChannel,
    TeamChannelMessage,
    TeamWorkspace,
    TeamWorkspaceInvitation,
    TeamWorkspaceMembership,
    User,
)
from app.schemas import (
    TeamChannelCreate,
    TeamChannelMessageCreate,
    TeamChannelMessageResponse,
    TeamChannelResponse,
    TeamWorkspaceCreate,
    TeamWorkspaceInvitationCreate,
    TeamWorkspaceInvitationReply,
    TeamWorkspaceInvitationResponse,
    TeamWorkspaceMemberResponse,
    TeamWorkspaceResponse,
)
from app.security import get_current_user, require_project_access
from app.services.audit import record_activity

router = APIRouter(tags=["team workspaces"])


def _require_workspace_member(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID):
    workspace = db.get(TeamWorkspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Team workspace not found.")
    membership = db.scalar(
        select(TeamWorkspaceMembership).where(
            TeamWorkspaceMembership.team_workspace_id == workspace_id,
            TeamWorkspaceMembership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Team workspace not found.")
    return workspace, membership


def _require_workspace_owner(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID):
    workspace, _ = _require_workspace_member(db, workspace_id, user_id)
    if workspace.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Team workspace not found.")
    return workspace


def _workspace_response(db: Session, workspace: TeamWorkspace, role: str) -> dict:
    return {
        "team_workspace_id": workspace.team_workspace_id,
        "owner_id": workspace.owner_id,
        "name": workspace.name,
        "created_at": workspace.created_at,
        "membership_role": role,
        "member_count": db.scalar(
            select(func.count(TeamWorkspaceMembership.membership_id)).where(
                TeamWorkspaceMembership.team_workspace_id == workspace.team_workspace_id
            )
        ) or 0,
    }


def _invitation_response(
    invitation: TeamWorkspaceInvitation,
    workspace: TeamWorkspace,
    inviter: User,
    invitee: User,
) -> dict:
    return {
        "invitation_id": invitation.invitation_id,
        "team_workspace_id": invitation.team_workspace_id,
        "inviter_id": invitation.inviter_id,
        "invitee_id": invitation.invitee_id,
        "status": invitation.status,
        "created_at": invitation.created_at,
        "updated_at": invitation.updated_at,
        "workspace_name": workspace.name,
        "inviter_name": inviter.name,
        "invitee_name": invitee.name,
        "invitee_username": invitee.username or "",
        "invitee_email": invitee.email,
    }


def _channel_response(channel: TeamChannel, project_name: str | None) -> dict:
    return {
        "channel_id": channel.channel_id,
        "team_workspace_id": channel.team_workspace_id,
        "project_id": channel.project_id,
        "created_by": channel.created_by,
        "name": channel.name,
        "created_at": channel.created_at,
        "project_name": project_name,
    }


def _require_channel_access(db: Session, channel_id: uuid.UUID, user_id: uuid.UUID) -> TeamChannel:
    channel = db.get(TeamChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found.")
    if channel.project_id is not None:
        require_project_access(db, channel.project_id, user_id)
    else:
        _require_workspace_member(db, channel.team_workspace_id, user_id)
    return channel


@router.get("/api/team-workspaces", response_model=list[TeamWorkspaceResponse])
def list_team_workspaces(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(TeamWorkspace, TeamWorkspaceMembership.role)
        .join(
            TeamWorkspaceMembership,
            TeamWorkspaceMembership.team_workspace_id == TeamWorkspace.team_workspace_id,
        )
        .where(TeamWorkspaceMembership.user_id == user.user_id)
        .order_by(TeamWorkspace.created_at.desc())
    ).all()
    return [_workspace_response(db, workspace, role) for workspace, role in rows]


@router.post(
    "/api/team-workspaces",
    response_model=TeamWorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_team_workspace(
    payload: TeamWorkspaceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = TeamWorkspace(owner_id=user.user_id, name=payload.name)
    db.add(workspace)
    db.flush()
    db.add(
        TeamWorkspaceMembership(
            team_workspace_id=workspace.team_workspace_id,
            user_id=user.user_id,
            role="owner",
        )
    )
    record_activity(db, user.user_id, "team_workspace.created")
    db.commit()
    db.refresh(workspace)
    return _workspace_response(db, workspace, "owner")


@router.get(
    "/api/team-workspaces/{workspace_id}/members",
    response_model=list[TeamWorkspaceMemberResponse],
)
def list_team_workspace_members(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_workspace_member(db, workspace_id, user.user_id)
    rows = db.execute(
        select(TeamWorkspaceMembership, User)
        .join(User, User.user_id == TeamWorkspaceMembership.user_id)
        .where(TeamWorkspaceMembership.team_workspace_id == workspace_id)
        .order_by(TeamWorkspaceMembership.created_at)
    ).all()
    return [
        {
            "user_id": member.user_id,
            "username": member.username or "",
            "name": member.name,
            "email": member.email,
            "role": membership.role,
            "joined_at": membership.created_at,
        }
        for membership, member in rows
    ]


@router.post(
    "/api/team-workspaces/{workspace_id}/invitations",
    response_model=TeamWorkspaceInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_to_team_workspace(
    workspace_id: uuid.UUID,
    payload: TeamWorkspaceInvitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = _require_workspace_owner(db, workspace_id, user.user_id)
    identifier = payload.identifier.strip().casefold()
    if identifier.startswith("@") and identifier.count("@") == 1:
        identifier = identifier[1:]
    invitee = db.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == identifier,
                func.lower(User.username) == identifier,
            )
        )
    )
    if invitee is None:
        raise HTTPException(
            status_code=404,
            detail="No registered account matches that username or email address.",
        )
    if invitee.user_id == user.user_id:
        raise HTTPException(status_code=422, detail="You already own this team workspace.")
    membership = db.scalar(
        select(TeamWorkspaceMembership.membership_id).where(
            TeamWorkspaceMembership.team_workspace_id == workspace_id,
            TeamWorkspaceMembership.user_id == invitee.user_id,
        )
    )
    if membership is not None:
        raise HTTPException(status_code=409, detail="This user is already a team member.")

    invitation = db.scalar(
        select(TeamWorkspaceInvitation).where(
            TeamWorkspaceInvitation.team_workspace_id == workspace_id,
            TeamWorkspaceInvitation.invitee_id == invitee.user_id,
        )
    )
    now = datetime.now(timezone.utc)
    if invitation is not None and invitation.status == "pending":
        raise HTTPException(status_code=409, detail="This user already has a pending invitation.")
    if invitation is None:
        invitation = TeamWorkspaceInvitation(
            team_workspace_id=workspace_id,
            inviter_id=user.user_id,
            invitee_id=invitee.user_id,
            status="pending",
        )
        db.add(invitation)
        db.flush()
    else:
        invitation.inviter_id = user.user_id
        invitation.status = "pending"
        invitation.created_at = now
        invitation.updated_at = now
    record_activity(db, user.user_id, "team_workspace.invited")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This user already has a pending invitation.") from None
    db.refresh(invitation)
    return _invitation_response(invitation, workspace, user, invitee)


@router.get(
    "/api/team-workspaces/{workspace_id}/invitations",
    response_model=list[TeamWorkspaceInvitationResponse],
)
def list_team_workspace_invitations(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_workspace_owner(db, workspace_id, user.user_id)
    inviter = aliased(User)
    invitee = aliased(User)
    rows = db.execute(
        select(TeamWorkspaceInvitation, TeamWorkspace, inviter, invitee)
        .join(TeamWorkspace, TeamWorkspace.team_workspace_id == TeamWorkspaceInvitation.team_workspace_id)
        .join(inviter, inviter.user_id == TeamWorkspaceInvitation.inviter_id)
        .join(invitee, invitee.user_id == TeamWorkspaceInvitation.invitee_id)
        .where(
            TeamWorkspaceInvitation.team_workspace_id == workspace_id,
            TeamWorkspaceInvitation.status == "pending",
        )
    ).all()
    return [
        _invitation_response(invitation, workspace, inviter, invitee)
        for invitation, workspace, inviter, invitee in rows
    ]


@router.get(
    "/api/team-workspace-invitations",
    response_model=list[TeamWorkspaceInvitationResponse],
)
def list_received_team_workspace_invitations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inviter = aliased(User)
    invitee = aliased(User)
    rows = db.execute(
        select(TeamWorkspaceInvitation, TeamWorkspace, inviter, invitee)
        .join(TeamWorkspace, TeamWorkspace.team_workspace_id == TeamWorkspaceInvitation.team_workspace_id)
        .join(inviter, inviter.user_id == TeamWorkspaceInvitation.inviter_id)
        .join(invitee, invitee.user_id == TeamWorkspaceInvitation.invitee_id)
        .where(
            TeamWorkspaceInvitation.invitee_id == user.user_id,
            TeamWorkspaceInvitation.status == "pending",
        )
        .order_by(TeamWorkspaceInvitation.created_at.desc())
    ).all()
    return [
        _invitation_response(invitation, workspace, inviter, invitee)
        for invitation, workspace, inviter, invitee in rows
    ]


@router.post(
    "/api/team-workspace-invitations/{invitation_id}/respond",
    response_model=TeamWorkspaceInvitationResponse,
)
def respond_to_team_workspace_invitation(
    invitation_id: uuid.UUID,
    payload: TeamWorkspaceInvitationReply,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    invitation = db.scalar(
        select(TeamWorkspaceInvitation).where(
            TeamWorkspaceInvitation.invitation_id == invitation_id,
            TeamWorkspaceInvitation.invitee_id == user.user_id,
        )
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Team workspace invitation not found.")
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(TeamWorkspaceInvitation)
        .where(
            TeamWorkspaceInvitation.invitation_id == invitation_id,
            TeamWorkspaceInvitation.invitee_id == user.user_id,
            TeamWorkspaceInvitation.status == "pending",
        )
        .values(status=payload.response, updated_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="This invitation has already been answered.")
    if payload.response == "accepted":
        db.add(
            TeamWorkspaceMembership(
                team_workspace_id=invitation.team_workspace_id,
                user_id=user.user_id,
                role="member",
            )
        )
    record_activity(db, user.user_id, f"team_workspace.invitation_{payload.response}")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You are already a member of this team workspace.") from None
    workspace = db.get(TeamWorkspace, invitation.team_workspace_id)
    inviter = db.get(User, invitation.inviter_id)
    if workspace is None or inviter is None:
        raise HTTPException(status_code=404, detail="Team workspace invitation not found.")
    db.refresh(invitation)
    return _invitation_response(invitation, workspace, inviter, user)


@router.delete(
    "/api/team-workspaces/{workspace_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_team_workspace_member(
    workspace_id: uuid.UUID,
    member_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = _require_workspace_owner(db, workspace_id, user.user_id)
    if member_id == workspace.owner_id:
        raise HTTPException(status_code=422, detail="The workspace owner cannot be removed.")
    membership = db.scalar(
        select(TeamWorkspaceMembership).where(
            TeamWorkspaceMembership.team_workspace_id == workspace_id,
            TeamWorkspaceMembership.user_id == member_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Team member not found.")
    db.delete(membership)
    db.commit()


@router.get(
    "/api/team-workspaces/{workspace_id}/channels",
    response_model=list[TeamChannelResponse],
)
def list_team_channels(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if db.get(TeamWorkspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Team workspace not found.")
    membership = db.scalar(
        select(TeamWorkspaceMembership.membership_id).where(
            TeamWorkspaceMembership.team_workspace_id == workspace_id,
            TeamWorkspaceMembership.user_id == user.user_id,
        )
    )
    query = select(TeamChannel, ResearchProject.project_name).outerjoin(
        ResearchProject, ResearchProject.project_id == TeamChannel.project_id
    ).where(TeamChannel.team_workspace_id == workspace_id)
    if membership is None:
        project_ids = select(ResearchProject.project_id).where(
            ResearchProject.team_workspace_id == workspace_id,
            or_(
                ResearchProject.user_id == user.user_id,
                ResearchProject.project_id.in_(
                    select(ProjectInvitation.project_id).where(
                        ProjectInvitation.invitee_id == user.user_id,
                        ProjectInvitation.status == "accepted",
                    )
                ),
            ),
        )
        query = query.where(TeamChannel.project_id.in_(project_ids))
    rows = db.execute(query.order_by(TeamChannel.created_at, TeamChannel.name)).all()
    return [_channel_response(channel, project_name) for channel, project_name in rows]


@router.post(
    "/api/team-workspaces/{workspace_id}/channels",
    response_model=TeamChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_team_channel(
    workspace_id: uuid.UUID,
    payload: TeamChannelCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_workspace_member(db, workspace_id, user.user_id)
    if payload.project_id is not None:
        project = db.get(ResearchProject, payload.project_id)
        if project is None or project.team_workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Project not found in this team workspace.")
    channel = TeamChannel(
        team_workspace_id=workspace_id,
        project_id=payload.project_id,
        created_by=user.user_id,
        name=payload.name,
    )
    db.add(channel)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A channel with this name already exists.") from None
    db.refresh(channel)
    project_name = db.scalar(
        select(ResearchProject.project_name).where(
            ResearchProject.project_id == payload.project_id
        )
    ) if payload.project_id is not None else None
    return _channel_response(channel, project_name)


@router.get(
    "/api/team-channels/{channel_id}/messages",
    response_model=list[TeamChannelMessageResponse],
)
def get_team_channel_messages(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    channel = _require_channel_access(db, channel_id, user.user_id)
    rows = db.execute(
        select(TeamChannelMessage, User.name)
        .join(User, User.user_id == TeamChannelMessage.sender_id)
        .where(TeamChannelMessage.channel_id == channel.channel_id)
        .order_by(TeamChannelMessage.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "message_id": message.message_id,
            "channel_id": message.channel_id,
            "sender_id": message.sender_id,
            "sender_name": sender_name,
            "content": message.content,
            "created_at": message.created_at,
        }
        for message, sender_name in reversed(rows)
    ]


@router.post(
    "/api/team-channels/{channel_id}/messages",
    response_model=TeamChannelMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def send_team_channel_message(
    channel_id: uuid.UUID,
    payload: TeamChannelMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    channel = _require_channel_access(db, channel_id, user.user_id)
    message = TeamChannelMessage(
        channel_id=channel.channel_id,
        sender_id=user.user_id,
        content=payload.content,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return {
        "message_id": message.message_id,
        "channel_id": message.channel_id,
        "sender_id": message.sender_id,
        "sender_name": user.name,
        "content": message.content,
        "created_at": message.created_at,
    }
