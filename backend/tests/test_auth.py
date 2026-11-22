import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import Settings
from app.models import AuthRateLimit, User, UserActivity
from app.routers import auth
from app.schemas import ChangePasswordRequest, LoginRequest, ProfileUpdate, RegisterRequest
from app.security import hash_password, verify_password
from app.services import rate_limit


@pytest.fixture
def auth_db():
    engine = create_engine("sqlite://")
    for table in (AuthRateLimit.__table__, User.__table__, UserActivity.__table__):
        table.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def make_request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/auth/login",
            "headers": [],
            "client": ("203.0.113.15", 12345),
            "server": ("testserver", 443),
        }
    )


def test_user_login_throttles_attempts_and_clears_counters_after_success(
    auth_db: Session, monkeypatch
):
    user = User(
        email="researcher@example.com",
        name="Researcher",
        password_hash=hash_password("safe password"),
    )
    auth_db.add(user)
    auth_db.commit()
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: Settings(jwt_secret="test-secret"),
    )
    monkeypatch.setattr(auth, "create_access_token", lambda _: "user-token")
    request = make_request()

    with pytest.raises(HTTPException) as error:
        auth.login(
            LoginRequest(email=user.email, password="wrong password"),
            request,
            auth_db,
        )
    assert error.value.status_code == 401

    result = auth.login(
        LoginRequest(email=user.email, password="safe password"),
        request,
        auth_db,
    )
    assert result.access_token == "user-token"
    assert auth_db.scalar(select(AuthRateLimit)) is None

    for _ in range(5):
        with pytest.raises(HTTPException) as error:
            auth.login(
                LoginRequest(email=user.email, password="wrong password"),
                request,
                auth_db,
            )
        assert error.value.status_code == 401

    with pytest.raises(HTTPException) as error:
        auth.login(
            LoginRequest(email=user.email, password="wrong password"),
            request,
            auth_db,
        )

    assert error.value.status_code == 429


def test_registration_creates_unique_username(auth_db: Session, monkeypatch):
    monkeypatch.setattr(auth, "create_access_token", lambda _: "user-token")
    payload = RegisterRequest(
        email="researcher@example.com",
        username="Researcher_1",
        name="Researcher",
        password="a safe password",
    )
    result = auth.register(payload, auth_db)
    assert result.user.username == "researcher_1"

    with pytest.raises(HTTPException) as duplicate:
        auth.register(
            RegisterRequest(
                email="another@example.com",
                username="RESEARCHER_1",
                name="Another",
                password="another safe password",
            ),
            auth_db,
        )
    assert duplicate.value.status_code == 409


def test_profile_update_changes_display_name_username_and_picture(auth_db: Session):
    user = User(
        email="researcher@example.com",
        username="researcher",
        name="Researcher",
        password_hash=hash_password("safe password"),
    )
    auth_db.add(user)
    auth_db.commit()

    updated = auth.update_profile(
        ProfileUpdate(
            name="Research Writer",
            username="Research.Writer",
            profile_picture="data:image/png;base64,iVBORw0KGgo=",
        ),
        auth_db,
        user,
    )

    assert updated.name == "Research Writer"
    assert updated.username == "research.writer"
    assert updated.profile_picture == "data:image/png;base64,iVBORw0KGgo="


def test_profile_update_rejects_an_existing_username(auth_db: Session):
    current = User(
        email="current@example.com",
        username="current",
        name="Current",
        password_hash="hashed",
    )
    other = User(
        email="other@example.com",
        username="other",
        name="Other",
        password_hash="hashed",
    )
    auth_db.add_all((current, other))
    auth_db.commit()

    with pytest.raises(HTTPException) as error:
        auth.update_profile(ProfileUpdate(username="OTHER"), auth_db, current)

    assert error.value.status_code == 409


def test_user_can_change_password_but_wrong_current_password_is_rejected(auth_db: Session):
    user = User(
        email="researcher@example.com",
        name="Researcher",
        password_hash=hash_password("current research passphrase"),
    )
    auth_db.add(user)
    auth_db.commit()

    with pytest.raises(HTTPException) as error:
        auth.change_password(
            ChangePasswordRequest(
                current_password="incorrect current",
                new_password="a different research passphrase",
            ),
            auth_db,
            user,
        )
    assert error.value.status_code == 400

    auth.change_password(
        ChangePasswordRequest(
            current_password="current research passphrase",
            new_password="a different research passphrase",
        ),
        auth_db,
        user,
    )
    updated = auth_db.get(User, user.user_id)
    assert verify_password("a different research passphrase", updated.password_hash)
    assert not verify_password("current research passphrase", updated.password_hash)
