import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import ensure_project_team_workspace_column, get_db
from app.models import (
    DirectMessage,
    Notification,
    ProjectActivity,
    ProjectInvitation,
    ResearchProject,
    TeamChannel,
    TeamChannelMessage,
    TeamWorkspace,
    TeamWorkspaceInvitation,
    TeamWorkspaceMembership,
    User,
    UserActivity,
)
from app.routers import collaboration, projects, team_workspaces
from app.security import bearer_scheme, get_current_user, require_project_access


@pytest.fixture
def team_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'team-workspaces.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        TeamWorkspaceMembership,
        TeamWorkspaceInvitation,
        ResearchProject,
        ProjectInvitation,
        DirectMessage,
        Notification,
        TeamChannel,
        TeamChannelMessage,
        UserActivity,
        ProjectActivity,
    ):
        model.__table__.create(engine)
    with Session(engine) as db:
        owner = User(
            email="owner@example.com",
            username="owner",
            name="Workspace owner",
            password_hash="hashed",
        )
        member = User(
            email="member@example.com",
            username="member",
            name="Workspace member",
            password_hash="hashed",
        )
        external = User(
            email="external@example.com",
            username="external",
            name="External collaborator",
            password_hash="hashed",
        )
        outsider = User(
            email="outsider@example.com",
            username="outsider",
            name="Unrelated user",
            password_hash="hashed",
        )
        db.add_all((owner, member, external, outsider))
        db.commit()
        yield engine, owner.user_id, member.user_id, external.user_id, outsider.user_id
    engine.dispose()


def _client(engine, user_ids):
    app = FastAPI()
    app.include_router(projects.router)
    app.include_router(collaboration.router)
    app.include_router(team_workspaces.router)

    def test_db():
        with Session(engine) as db:
            yield db

    def authenticated_user(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        db: Session = Depends(get_db),
    ):
        return db.get(User, user_ids[credentials.credentials])

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user] = authenticated_user
    client = TestClient(app)
    headers = {
        name: {"Authorization": f"Bearer {name}"}
        for name in user_ids
    }
    return client, headers


def test_workspace_project_membership_and_channels_are_scoped(team_database):
    engine, owner_id, member_id, external_id, outsider_id = team_database
    user_ids = {
        "owner": owner_id,
        "member": member_id,
        "external": external_id,
        "outsider": outsider_id,
    }
    client, headers = _client(engine, user_ids)
    with client:
        created = client.post(
            "/api/team-workspaces",
            headers=headers["owner"],
            json={"name": "Cancer Research"},
        )
        assert created.status_code == 201
        workspace_id = created.json()["team_workspace_id"]
        invitation = client.post(
            f"/api/team-workspaces/{workspace_id}/invitations",
            headers=headers["owner"],
            json={"identifier": "MEMBER@example.com"},
        )
        assert invitation.status_code == 201
        invitation_id = invitation.json()["invitation_id"]
        assert client.get("/api/team-workspaces", headers=headers["member"]).json() == []
        assert client.get("/api/team-workspace-invitations", headers=headers["member"]).json()[0]["workspace_name"] == "Cancer Research"
        assert client.get(
            f"/api/team-workspaces/{workspace_id}/invitations",
            headers=headers["owner"],
        ).status_code == 200

        joined = client.post(
            f"/api/team-workspace-invitations/{invitation_id}/respond",
            headers=headers["member"],
            json={"response": "accepted"},
        )
        assert joined.status_code == 200
        assert client.get("/api/team-workspaces", headers=headers["member"]).json()[0]["membership_role"] == "member"

        project = client.post(
            "/api/projects",
            headers=headers["owner"],
            json={
                "project_name": "Literature review",
                "description": "",
                "team_workspace_id": workspace_id,
            },
        )
        assert project.status_code == 201
        project_id = project.json()["project_id"]
        assert client.get("/api/projects", headers=headers["member"]).json()[0]["project_id"] == project_id
        channel = client.post(
            f"/api/team-workspaces/{workspace_id}/channels",
            headers=headers["member"],
            json={"name": "#project-chat", "project_id": project_id},
        )
        assert channel.status_code == 201
        assert channel.json()["name"] == "project-chat"
        duplicate_channel = client.post(
            f"/api/team-workspaces/{workspace_id}/channels",
            headers=headers["owner"],
            json={"name": "project-chat", "project_id": project_id},
        )
        assert duplicate_channel.status_code == 409
        forbidden_channel = client.post(
            f"/api/team-workspaces/{workspace_id}/channels",
            headers=headers["external"],
            json={"name": "guest-channel"},
        )
        assert forbidden_channel.status_code == 404
        wrong_workspace_project = client.post(
            f"/api/team-workspaces/{workspace_id}/channels",
            headers=headers["member"],
            json={"name": "wrong-project", "project_id": str(outsider_id)},
        )
        assert wrong_workspace_project.status_code == 404

        project_invite = client.post(
            f"/api/projects/{project_id}/invitations",
            headers=headers["owner"],
            json={"identifier": "external"},
        )
        assert project_invite.status_code == 201
        accepted = client.post(
            f"/api/invitations/{project_invite.json()['invitation_id']}/respond",
            headers=headers["external"],
            json={"response": "accepted"},
        )
        assert accepted.status_code == 200
        assert client.get("/api/team-workspaces", headers=headers["external"]).json() == []
        assert client.get("/api/projects", headers=headers["external"]).json()[0]["project_id"] == project_id


def test_external_project_guest_only_sees_project_channel(team_database):
    engine, owner_id, member_id, external_id, outsider_id = team_database
    with Session(engine) as db:
        workspace = TeamWorkspace(owner_id=owner_id, name="Lab")
        db.add(workspace)
        db.flush()
        db.add_all(
            (
                TeamWorkspaceMembership(
                    team_workspace_id=workspace.team_workspace_id,
                    user_id=owner_id,
                    role="owner",
                ),
                TeamWorkspaceMembership(
                    team_workspace_id=workspace.team_workspace_id,
                    user_id=member_id,
                    role="member",
                ),
            )
        )
        project = ResearchProject(
            user_id=owner_id,
            team_workspace_id=workspace.team_workspace_id,
            project_name="Shared project",
        )
        db.add(project)
        db.flush()
        invitation = ProjectInvitation(
            project_id=project.project_id,
            inviter_id=owner_id,
            invitee_id=external_id,
            status="accepted",
        )
        db.add(invitation)
        workspace_channel = TeamChannel(
            team_workspace_id=workspace.team_workspace_id,
            created_by=owner_id,
            name="announcements",
        )
        project_channel = TeamChannel(
            team_workspace_id=workspace.team_workspace_id,
            project_id=project.project_id,
            created_by=owner_id,
            name="project-chat",
        )
        db.add_all((workspace_channel, project_channel))
        db.commit()
        workspace_id = workspace.team_workspace_id
        project_id = project.project_id
        workspace_channel_id = workspace_channel.channel_id
        project_channel_id = project_channel.channel_id

    client, headers = _client(
        engine,
        {
            "owner": owner_id,
            "member": member_id,
            "external": external_id,
            "outsider": outsider_id,
        },
    )
    with client:
        channels = client.get(
            f"/api/team-workspaces/{workspace_id}/channels",
            headers=headers["external"],
        )
        assert channels.status_code == 200
        assert [channel["name"] for channel in channels.json()] == ["project-chat"]
        assert client.get(
            f"/api/team-channels/{workspace_channel_id}/messages",
            headers=headers["external"],
        ).status_code == 404
        sent = client.post(
            f"/api/team-channels/{project_channel_id}/messages",
            headers=headers["external"],
            json={"content": "I can see this project conversation."},
        )
        assert sent.status_code == 201
        assert sent.json()["sender_name"] == "External collaborator"
        assert client.get(
            f"/api/team-channels/{project_channel_id}/messages",
            headers=headers["outsider"],
        ).status_code == 404


def test_workspace_member_removal_revokes_team_project_access(team_database):
    engine, owner_id, member_id, _, _ = team_database
    with Session(engine) as db:
        workspace = TeamWorkspace(owner_id=owner_id, name="Lab")
        db.add(workspace)
        db.flush()
        db.add_all(
            (
                TeamWorkspaceMembership(
                    team_workspace_id=workspace.team_workspace_id,
                    user_id=owner_id,
                    role="owner",
                ),
                TeamWorkspaceMembership(
                    team_workspace_id=workspace.team_workspace_id,
                    user_id=member_id,
                    role="member",
                ),
            )
        )
        project = ResearchProject(
            user_id=owner_id,
            team_workspace_id=workspace.team_workspace_id,
            project_name="Shared project",
        )
        db.add(project)
        db.commit()
        workspace_id = workspace.team_workspace_id
        project_id = project.project_id
    client, headers = _client(engine, {"owner": owner_id, "member": member_id})
    with client:
        removed = client.delete(
            f"/api/team-workspaces/{workspace_id}/members/{member_id}",
            headers=headers["owner"],
        )
        assert removed.status_code == 204
        assert client.get("/api/projects", headers=headers["member"]).json() == []
        with Session(engine) as db:
            with pytest.raises(HTTPException) as access_error:
                require_project_access(db, project_id, member_id)
        assert getattr(access_error.value, "status_code", None) == 404


def test_project_workspace_column_migration_is_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-projects.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE team_workspaces (team_workspace_id CHAR(32) PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE research_projects (project_id CHAR(32) PRIMARY KEY, "
                "user_id CHAR(32) NOT NULL, project_name VARCHAR(160) NOT NULL)"
            )
        )
    ensure_project_team_workspace_column(engine)
    ensure_project_team_workspace_column(engine)
    assert "team_workspace_id" in {
        column["name"] for column in inspect(engine).get_columns("research_projects")
    }
    engine.dispose()
