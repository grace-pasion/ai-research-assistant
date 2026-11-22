import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import Settings
from app.models import (
    AuthRateLimit,
    Conversation,
    Document,
    ProjectPaper,
    ResearchProject,
    User,
    UserActivity,
)
from app.routers import admin
from app.schemas import AdminLoginRequest
from app.security import get_current_admin, hash_password
from app.services import rate_limit


@pytest.fixture
def admin_db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in (
        AuthRateLimit.__table__,
        User.__table__,
        ResearchProject.__table__,
        Document.__table__,
        ProjectPaper.__table__,
        Conversation.__table__,
        UserActivity.__table__,
    ):
        table.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def create_user(db: Session, email: str, password: str = "safe password") -> User:
    user = User(email=email, name=email.split("@")[0], password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/admin/auth/login",
            "headers": [],
            "client": ("203.0.113.15", 12345),
            "server": ("testserver", 443),
        }
    )


def test_admin_access_uses_case_insensitive_email_allowlist(monkeypatch):
    settings = Settings(admin_emails="Admin@Example.com, second@example.com")
    monkeypatch.setattr("app.security.get_settings", lambda: settings)
    admin_user = User(email="admin@example.com", name="Admin")
    regular_user = User(email="user@example.com", name="User")

    assert get_current_admin(admin_user) is admin_user
    with pytest.raises(HTTPException) as error:
        get_current_admin(regular_user)
    assert error.value.status_code == 403


def test_admin_login_rejects_non_allowlisted_account(admin_db: Session, monkeypatch):
    user = create_user(admin_db, "user@example.com")
    monkeypatch.setattr(admin, "consume_auth_attempt", lambda *args: None)
    monkeypatch.setattr(
        admin,
        "get_settings",
        lambda: Settings(admin_emails="admin@example.com"),
    )

    with pytest.raises(HTTPException) as error:
        admin.admin_login(
            AdminLoginRequest(email=user.email, password="safe password"),
            make_request(),
            admin_db,
        )

    assert error.value.status_code == 401


def test_admin_login_records_metadata_without_credentials(admin_db: Session, monkeypatch):
    user = create_user(admin_db, "admin@example.com")
    monkeypatch.setattr(admin, "consume_auth_attempt", lambda *args: None)
    monkeypatch.setattr(admin, "clear_auth_attempts", lambda *args: None)
    monkeypatch.setattr(
        admin,
        "get_settings",
        lambda: Settings(admin_emails="admin@example.com"),
    )
    monkeypatch.setattr(admin, "create_access_token", lambda _: "admin-token")

    result = admin.admin_login(
        AdminLoginRequest(email=user.email, password="safe password"),
        make_request(),
        admin_db,
    )

    activity = admin_db.scalar(select(UserActivity))
    assert result.access_token == "admin-token"
    assert activity is not None
    assert activity.action == "admin.login"
    assert activity.details == {}


def test_admin_login_enforces_rate_limit(admin_db: Session, monkeypatch):
    user = create_user(admin_db, "admin@example.com")
    monkeypatch.setattr(
        admin,
        "get_settings",
        lambda: Settings(admin_emails="admin@example.com"),
    )
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: Settings(jwt_secret="test-secret"),
    )
    request = make_request()

    for _ in range(5):
        with pytest.raises(HTTPException) as error:
            admin.admin_login(
                AdminLoginRequest(email=user.email, password="wrong password"),
                request,
                admin_db,
            )
        assert error.value.status_code == 401

    with pytest.raises(HTTPException) as error:
        admin.admin_login(
            AdminLoginRequest(email=user.email, password="wrong password"),
            request,
            admin_db,
        )

    assert error.value.status_code == 429


def test_admin_user_listing_returns_counts_and_activity_without_content(
    admin_db: Session, monkeypatch
):
    admin_user = create_user(admin_db, "admin@example.com")
    target = create_user(admin_db, "researcher@example.com")
    project = ResearchProject(
        user_id=target.user_id,
        project_name="Research",
        description="",
    )
    db_document_id = uuid.uuid4()
    admin_db.add(project)
    admin_db.flush()
    admin_db.add_all(
        [
            Document(
                document_id=db_document_id,
                project_id=project.project_id,
                filename="private-name.pdf",
                file_type="pdf",
                storage_path="test/path",
                file_size=123,
                processing_status="ready",
            ),
            ProjectPaper(project_id=project.project_id, paper_id=uuid.uuid4()),
            Conversation(
                user_id=target.user_id,
                project_id=project.project_id,
                title="Research conversation",
            ),
            UserActivity(
                user_id=target.user_id,
                action="assistant.draft_requested",
                details={"mode": "question"},
            ),
        ]
    )
    admin_db.commit()

    users = admin.list_users(limit=50, offset=0, db=admin_db, admin=admin_user)
    summary = next(item for item in users.users if item.user_id == target.user_id)
    activities = admin.list_activity(
        user_id=target.user_id,
        limit=50,
        offset=0,
        db=admin_db,
        admin=admin_user,
    )

    assert summary.project_count == 1
    assert summary.document_count == 1
    assert summary.saved_paper_count == 1
    assert summary.conversation_count == 1
    assert activities.total == 1
    assert activities.events[0].details == {"mode": "question"}
    assert "private-name.pdf" not in str(activities.events[0].model_dump())


def test_admin_hard_delete_removes_files_and_user_activity_cascades(
    admin_db: Session, monkeypatch
):
    admin_user = create_user(admin_db, "admin@example.com")
    target = create_user(admin_db, "researcher@example.com")
    project = ResearchProject(user_id=target.user_id, project_name="Research", description="")
    admin_db.add(project)
    admin_db.flush()
    admin_db.add(
        Document(
            project_id=project.project_id,
            filename="private.pdf",
            file_type="pdf",
            storage_path="supabase://research-documents/object.pdf",
            file_size=123,
            processing_status="ready",
        )
    )
    admin_db.add(UserActivity(user_id=target.user_id, action="document.uploaded", details={}))
    admin_db.commit()
    deleted_paths = []
    monkeypatch.setattr(admin, "delete_stored_document", deleted_paths.append)

    admin.delete_user(target.user_id, db=admin_db, admin=admin_user)
    admin_db.expire_all()

    assert deleted_paths == ["supabase://research-documents/object.pdf"]
    assert admin_db.get(User, target.user_id) is None
    assert admin_db.scalar(select(UserActivity.action)) == "admin.user_deleted"
    assert admin_db.scalar(
        select(UserActivity).where(UserActivity.user_id == target.user_id)
    ) is None


def test_admin_cannot_delete_own_account(admin_db: Session):
    admin_user = create_user(admin_db, "admin@example.com")

    with pytest.raises(HTTPException) as error:
        admin.delete_user(admin_user.user_id, db=admin_db, admin=admin_user)

    assert error.value.status_code == 400


def test_admin_delete_keeps_account_if_file_cleanup_fails(admin_db: Session, monkeypatch):
    admin_user = create_user(admin_db, "admin@example.com")
    target = create_user(admin_db, "researcher@example.com")
    project = ResearchProject(user_id=target.user_id, project_name="Research", description="")
    admin_db.add(project)
    admin_db.flush()
    admin_db.add(
        Document(
            project_id=project.project_id,
            filename="private.pdf",
            file_type="pdf",
            storage_path="supabase://research-documents/object.pdf",
            file_size=123,
            processing_status="ready",
        )
    )
    admin_db.commit()

    def fail_file_cleanup(_):
        raise RuntimeError("Storage unavailable")

    monkeypatch.setattr(admin, "delete_stored_document", fail_file_cleanup)

    with pytest.raises(HTTPException) as error:
        admin.delete_user(target.user_id, db=admin_db, admin=admin_user)

    assert error.value.status_code == 502
    assert admin_db.get(User, target.user_id) is not None
