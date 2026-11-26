import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProjectInvitation, ResearchProject, TeamWorkspaceMembership, User

_MENTION_PATTERN = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9._-]{3,32})")


def extract_mentioned_usernames(
    value: str,
    known_usernames: set[str] | None = None,
) -> set[str]:
    known = {username.casefold() for username in known_usernames or set()}
    mentioned = set()
    for candidate in _MENTION_PATTERN.findall(value):
        normalized = candidate.casefold()
        if normalized not in known:
            while normalized and normalized[-1] in "._-":
                normalized = normalized[:-1]
                if normalized in known:
                    break
        mentioned.add(normalized or candidate.casefold())
    return mentioned


def list_project_collaborators(
    db: Session,
    project: ResearchProject,
) -> list[tuple[User, str]]:
    roles: dict[uuid.UUID, str] = {project.user_id: "owner"}
    if project.team_workspace_id is not None:
        member_ids = db.scalars(
            select(TeamWorkspaceMembership.user_id).where(
                TeamWorkspaceMembership.team_workspace_id == project.team_workspace_id
            )
        ).all()
        for member_id in member_ids:
            roles.setdefault(member_id, "edit")
    invitations = db.execute(
        select(ProjectInvitation.invitee_id, ProjectInvitation.role).where(
            ProjectInvitation.project_id == project.project_id,
            ProjectInvitation.status == "accepted",
        )
    ).all()
    for user_id, role in invitations:
        roles.setdefault(user_id, role)
    if not roles:
        return []
    users = db.scalars(
        select(User)
        .where(User.user_id.in_(roles))
        .order_by(func.lower(User.username), User.user_id)
    ).all()
    return [(user, roles[user.user_id]) for user in users]
