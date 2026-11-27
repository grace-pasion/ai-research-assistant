import uuid

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import (
    ensure_project_collaboration_columns,
    ensure_user_profile_picture_column,
    ensure_user_username_column,
    get_db,
)
from app.models import (
    DirectMessage,
    Document,
    LatexWorkspace,
    Notification,
    NotificationPreference,
    ProjectActivity,
    ProjectFileVersion,
    ProjectInvitation,
    ResearchProject,
    TeamWorkspace,
    TeamWorkspaceMembership,
    User,
    UserActivity,
)
from app.routers.collaboration import (
    invite_to_project,
    list_message_threads,
    list_notifications,
    list_project_invitations,
    revoke_project_invitation,
    respond_to_invitation,
    send_direct_message,
    get_message_thread,
    unread_count,
    update_project_invitation_role,
)
from app.routers import collaboration, documents, latex, notifications, projects
from app.routers.projects import list_projects
from app.schemas import (
    DirectMessageCreate,
    InvitationResponseRequest,
    ProjectInvitationCreate,
    ProjectInvitationRoleUpdate,
)
from app.security import bearer_scheme, get_current_user, require_project_access
from app.services.notification_preferences import add_notification_if_enabled


@pytest.fixture
def collaboration_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'collaboration.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        TeamWorkspaceMembership,
        ResearchProject,
        ProjectInvitation,
        Document,
        DirectMessage,
        LatexWorkspace,
        ProjectFileVersion,
        Notification,
        NotificationPreference,
        UserActivity,
        ProjectActivity,
    ):
        model.__table__.create(engine)
    with Session(engine) as db:
        owner = User(
            email="owner@example.com",
            username="owner",
            name="Project owner",
            password_hash="hashed",
        )
        invitee = User(
            email="invitee@example.com",
            username="invitee",
            name="Project colleague",
            password_hash="hashed",
        )
        outsider = User(
            email="outsider@example.com",
            username="outsider",
            name="Outsider",
            password_hash="hashed",
        )
        db.add_all((owner, invitee, outsider))
        db.flush()
        project = ResearchProject(
            user_id=owner.user_id,
            project_name="Breast cancer review",
            description="Shared evidence review",
        )
        db.add(project)
        db.commit()
        yield db, owner, invitee, outsider, project
    engine.dispose()


def test_project_invitation_grants_access_only_after_acceptance(collaboration_db):
    db, owner, invitee, outsider, project = collaboration_db

    invitation = invite_to_project(
        project.project_id,
        ProjectInvitationCreate(identifier="@Invitee"),
        db,
        owner,
    )
    assert invitation["status"] == "pending"
    with pytest.raises(HTTPException) as pending_access:
        require_project_access(db, project.project_id, invitee.user_id)
    assert pending_access.value.status_code == 404
    assert [item.project_id for item in list_projects(db, invitee)] == []

    accepted = respond_to_invitation(
        invitation["invitation_id"],
        InvitationResponseRequest(response="accepted"),
        db,
        invitee,
    )
    assert accepted["status"] == "accepted"
    assert require_project_access(db, project.project_id, invitee.user_id).project_id == project.project_id
    assert [item.project_id for item in list_projects(db, invitee)] == [project.project_id]
    collaborators = collaboration.list_collaborators(project.project_id, db, invitee)
    assert {item["username"]: item["role"] for item in collaborators} == {
        "owner": "owner",
        "invitee": "edit",
    }
    with pytest.raises(HTTPException) as outsider_access:
        require_project_access(db, project.project_id, outsider.user_id)
    assert outsider_access.value.status_code == 404

    owner_notifications = list_notifications(db, owner)
    assert len(owner_notifications) == 1
    assert owner_notifications[0]["kind"] == "invitation_response"
    assert owner_notifications[0]["invitation_status"] == "accepted"

    with pytest.raises(HTTPException) as answered:
        respond_to_invitation(
            invitation["invitation_id"],
            InvitationResponseRequest(response="declined"),
            db,
            invitee,
        )
    assert answered.value.status_code == 409


def test_project_roles_control_shared_edits_and_can_be_changed_by_owner(collaboration_db):
    db, owner, invitee, _, project = collaboration_db
    invitation = invite_to_project(
        project.project_id,
        ProjectInvitationCreate(identifier=invitee.username, role="read"),
        db,
        owner,
    )
    assert list_notifications(db, invitee)[0]["invitation_role"] == "read"
    respond_to_invitation(
        invitation["invitation_id"],
        InvitationResponseRequest(response="accepted"),
        db,
        invitee,
    )

    assert invitation["role"] == "read"
    assert list_projects(db, invitee)[0].access_role == "read"
    assert latex.get_latex_workspace(project.project_id, db, invitee).main_tex
    with pytest.raises(HTTPException) as read_only:
        latex.save_latex_workspace(
            project.project_id,
            latex.LatexWorkspaceUpdate(main_tex="not allowed", references_bib=""),
            db,
            invitee,
        )
    assert read_only.value.status_code == 403

    changed = update_project_invitation_role(
        project.project_id,
        invitation["invitation_id"],
        ProjectInvitationRoleUpdate(role="edit"),
        db,
        owner,
    )
    assert changed["role"] == "edit"
    assert list_projects(db, invitee)[0].access_role == "edit"
    saved = latex.save_latex_workspace(
        project.project_id,
        latex.LatexWorkspaceUpdate(main_tex="editor draft", references_bib=""),
        db,
        invitee,
    )
    assert saved.main_tex == "editor draft"


def test_invitation_lookup_accepts_email_and_rejects_unknown_users(collaboration_db):
    db, owner, invitee, _, project = collaboration_db

    invite_to_project(
        project.project_id,
        ProjectInvitationCreate(identifier="INVITEE@example.com"),
        db,
        owner,
    )
    with pytest.raises(HTTPException) as duplicate:
        invite_to_project(
            project.project_id,
            ProjectInvitationCreate(identifier=invitee.username),
            db,
            owner,
        )
    assert duplicate.value.status_code == 409

    other_project = ResearchProject(user_id=owner.user_id, project_name="Other")
    db.add(other_project)
    db.commit()
    with pytest.raises(HTTPException) as unknown:
        invite_to_project(
            other_project.project_id,
            ProjectInvitationCreate(identifier="not-a-user"),
            db,
            owner,
        )
    assert unknown.value.status_code == 404


def test_only_owner_can_manage_access_and_revoking_removes_access(collaboration_db):
    db, owner, invitee, outsider, project = collaboration_db
    invitation = invite_to_project(
        project.project_id,
        ProjectInvitationCreate(identifier=invitee.username),
        db,
        owner,
    )
    with pytest.raises(HTTPException) as not_owner:
        list_project_invitations(project.project_id, db, invitee)
    assert not_owner.value.status_code == 404
    with pytest.raises(HTTPException) as cannot_invite:
        invite_to_project(
            project.project_id,
            ProjectInvitationCreate(identifier=outsider.username),
            db,
            invitee,
        )
    assert cannot_invite.value.status_code == 404

    respond_to_invitation(
        invitation["invitation_id"],
        InvitationResponseRequest(response="accepted"),
        db,
        invitee,
    )
    require_project_access(db, project.project_id, invitee.user_id)
    assert len(list_project_invitations(project.project_id, db, owner)) == 1
    revoke_project_invitation(project.project_id, invitation["invitation_id"], db, owner)
    with pytest.raises(HTTPException) as revoked:
        require_project_access(db, project.project_id, invitee.user_id)
    assert revoked.value.status_code == 404


def test_project_collaborators_can_reprocess_and_delete_shared_documents(collaboration_db, monkeypatch):
    db, owner, invitee, outsider, project = collaboration_db
    invitation = invite_to_project(
        project.project_id,
        ProjectInvitationCreate(identifier=invitee.username),
        db,
        owner,
    )
    respond_to_invitation(
        invitation["invitation_id"],
        InvitationResponseRequest(response="accepted"),
        db,
        invitee,
    )
    document = Document(
        project_id=project.project_id,
        filename="shared-notes.txt",
        file_type="txt",
        storage_path="local:test-document",
        file_size=12,
        processing_status="ready",
    )
    db.add(document)
    db.commit()
    document_id = document.document_id

    with pytest.raises(HTTPException) as unauthorized:
        documents.reprocess(document_id, BackgroundTasks(), db, outsider)
    assert unauthorized.value.status_code == 404

    reprocessed = documents.reprocess(document_id, BackgroundTasks(), db, invitee)
    assert reprocessed.processing_status == "processing"
    monkeypatch.setattr(documents, "delete_stored_document", lambda _path: None)
    documents.delete_document(document_id, db, invitee)
    assert db.get(Document, document_id) is None


def test_direct_messages_are_private_and_read_state_updates(collaboration_db):
    db, sender, recipient, outsider, _ = collaboration_db
    message = send_direct_message(
        recipient.user_id,
        DirectMessageCreate(content="Could you review the study notes?"),
        db,
        sender,
    )
    assert message.content == "Could you review the study notes?"
    assert unread_count(db, recipient) == {"count": 1}
    assert list_message_threads(db, recipient)[0]["unread_count"] == 1

    thread = get_message_thread(sender.user_id, db, recipient)
    assert [item.message_id for item in thread] == [message.message_id]
    assert thread[0].read_at is not None
    assert list_message_threads(db, recipient)[0]["unread_count"] == 0
    assert unread_count(db, recipient) == {"count": 0}
    assert db.query(Notification).filter_by(recipient_id=recipient.user_id).one().read_at is not None

    assert get_message_thread(sender.user_id, db, outsider) == []


@pytest.mark.parametrize(
    ("kind", "preference_field"),
    [
        ("project_invitation", "project_invitations"),
        ("invitation_response", "invitation_responses"),
        ("message", "direct_messages"),
        ("saved_search_alert", "saved_search_alerts"),
        ("annotation_mention", "annotation_mentions"),
        ("task_assigned", "task_assignments"),
    ],
)
def test_disabled_notification_preferences_suppress_only_the_selected_kind(
    collaboration_db,
    kind,
    preference_field,
):
    db, owner, recipient, _, _ = collaboration_db
    preferences = NotificationPreference(user_id=recipient.user_id)
    setattr(preferences, preference_field, False)
    db.add(preferences)
    db.commit()

    notification = Notification(
        recipient_id=recipient.user_id,
        actor_id=owner.user_id,
        kind=kind,
    )
    assert not add_notification_if_enabled(db, notification)
    db.commit()
    assert db.query(Notification).filter_by(recipient_id=recipient.user_id).count() == 0

    setattr(preferences, preference_field, True)
    assert add_notification_if_enabled(db, notification)
    db.commit()
    assert db.query(Notification).filter_by(recipient_id=recipient.user_id).count() == 1


def test_username_migration_backfills_existing_accounts(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    user_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users (user_id CHAR(32) PRIMARY KEY, email VARCHAR(320), "
                "name VARCHAR(120), password_hash VARCHAR(255))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO users (user_id, email, name, password_hash) "
                "VALUES (:user_id, 'legacy@example.com', 'Legacy', 'hash')"
            ),
            {"user_id": user_id.hex},
        )

    ensure_user_username_column(engine)
    ensure_user_profile_picture_column(engine)

    with engine.connect() as connection:
        username = connection.scalar(text("SELECT username FROM users WHERE user_id = :user_id"), {"user_id": user_id.hex})
        profile_picture = connection.scalar(
            text("SELECT profile_picture FROM users WHERE user_id = :user_id"),
            {"user_id": user_id.hex},
        )
    assert username.startswith("researcher_")
    assert len(username) == len("researcher_") + 12
    assert profile_picture is None
    engine.dispose()


def test_project_role_and_comment_author_migrations_preserve_existing_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old-collaboration.sqlite'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users (user_id CHAR(32) PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE project_invitations (invitation_id CHAR(32) PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE annotations (annotation_id CHAR(32) PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO project_invitations (invitation_id) VALUES ('old-invite')")
        )
        connection.execute(
            text("INSERT INTO annotations (annotation_id) VALUES ('old-comment')")
        )

    ensure_project_collaboration_columns(engine)
    ensure_project_collaboration_columns(engine)

    with engine.connect() as connection:
        role = connection.scalar(
            text("SELECT role FROM project_invitations WHERE invitation_id = 'old-invite'")
        )
        author = connection.scalar(
            text("SELECT created_by FROM annotations WHERE annotation_id = 'old-comment'")
        )
    assert role == "edit"
    assert author is None
    engine.dispose()


def test_collaboration_http_flow_and_realtime_workspace_access(collaboration_db):
    db, owner, invitee, _, project = collaboration_db
    app = FastAPI()
    app.include_router(projects.router)
    app.include_router(collaboration.router)
    app.include_router(notifications.router)
    app.include_router(latex.router)

    def test_db():
        with Session(db.get_bind()) as session:
            yield session

    tokens = {"owner-token": owner.user_id, "invitee-token": invitee.user_id}

    def authenticated_user(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        session: Session = Depends(get_db),
    ):
        return session.get(User, tokens[credentials.credentials])

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user] = authenticated_user
    owner_headers = {"Authorization": "Bearer owner-token"}
    invitee_headers = {"Authorization": "Bearer invitee-token"}

    with TestClient(app) as client:
        defaults = client.get("/api/notifications/preferences", headers=invitee_headers)
        assert defaults.status_code == 200
        assert all(defaults.json().values())
        invitee_preferences = defaults.json()
        invitee_preferences["project_invitations"] = False
        saved_preferences = client.put(
            "/api/notifications/preferences",
            headers=invitee_headers,
            json=invitee_preferences,
        )
        assert saved_preferences.status_code == 200
        assert saved_preferences.json()["project_invitations"] is False

        invite = client.post(
            f"/api/projects/{project.project_id}/invitations",
            headers=owner_headers,
            json={"identifier": invitee.username},
        )
        assert invite.status_code == 201
        db.expire_all()
        assert db.query(Notification).filter_by(
            recipient_id=invitee.user_id,
            kind="project_invitation",
        ).count() == 0
        invitation_id = invite.json()["invitation_id"]
        assert client.get("/api/projects", headers=invitee_headers).json() == []

        accepted = client.post(
            f"/api/invitations/{invitation_id}/respond",
            headers=invitee_headers,
            json={"response": "accepted"},
        )
        assert accepted.status_code == 200
        assert client.get("/api/projects", headers=invitee_headers).json()[0]["user_id"] == str(owner.user_id)
        assert client.get(
            "/api/notifications/preferences",
            headers=invitee_headers,
        ).json()["project_invitations"] is False

        initial = client.get(
            f"/api/projects/{project.project_id}/latex",
            headers=invitee_headers,
        )
        assert initial.status_code == 200
        saved = client.put(
            f"/api/projects/{project.project_id}/latex",
            headers=invitee_headers,
            json={
                "main_tex": "Shared draft",
                "references_bib": "",
                "expected_updated_at": initial.json()["updated_at"],
            },
        )
        assert saved.status_code == 200
        assert client.get(
            f"/api/projects/{project.project_id}/latex",
            headers=owner_headers,
        ).json()["main_tex"] == "Shared draft"

        owner_preferences = client.get(
            "/api/notifications/preferences",
            headers=owner_headers,
        ).json()
        owner_preferences["direct_messages"] = False
        assert client.put(
            "/api/notifications/preferences",
            headers=owner_headers,
            json=owner_preferences,
        ).status_code == 200
        message = client.post(
            f"/api/messages/{owner.user_id}",
            headers=invitee_headers,
            json={"content": "Please review the shared draft."},
        )
        assert message.status_code == 201
        thread = client.get(
            f"/api/messages/{invitee.user_id}",
            headers=owner_headers,
        )
        assert thread.status_code == 200
        assert thread.json()[0]["content"] == "Please review the shared draft."
        assert thread.json()[0]["read_at"] is not None
        db.expire_all()
        assert db.query(Notification).filter_by(
            recipient_id=owner.user_id,
            kind="message",
        ).count() == 0

        owner_edit = client.patch(
            f"/api/projects/{project.project_id}",
            headers=invitee_headers,
            json={"project_name": "Not allowed", "description": ""},
        )
        assert owner_edit.status_code == 404
        revoked = client.delete(
            f"/api/projects/{project.project_id}/invitations/{invitation_id}",
            headers=owner_headers,
        )
        assert revoked.status_code == 204
        assert client.get("/api/projects", headers=invitee_headers).json() == []
        assert client.get(
            f"/api/projects/{project.project_id}/latex",
            headers=invitee_headers,
        ).status_code == 404
