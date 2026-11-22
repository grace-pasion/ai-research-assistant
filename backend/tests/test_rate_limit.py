from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import Settings
from app.models import AuthRateLimit, DailyEmbeddingUsage, DailyPromptUsage, User
from app.routers import assistant as assistant_router
from app.routers import usage as usage_router
from app.schemas import AskRequest
from app.services import rate_limit


def make_request(client_ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/assistant/draft",
            "headers": [],
            "client": (client_ip, 12345),
            "server": ("testserver", 443),
        }
    )


@pytest.fixture
def prompt_usage_db():
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    AuthRateLimit.__table__.create(engine)
    DailyPromptUsage.__table__.create(engine)
    DailyEmbeddingUsage.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_daily_limit_allows_twenty_prompts_then_returns_429(
    prompt_usage_db: Session, monkeypatch
):
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: Settings(jwt_secret="test-secret"),
    )
    request = make_request("203.0.113.15")
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)

    for _ in range(20):
        rate_limit.consume_daily_prompt(prompt_usage_db, request, now)

    with pytest.raises(HTTPException) as error:
        rate_limit.consume_daily_prompt(prompt_usage_db, request, now)

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == str(12 * 60 * 60)
    usage = prompt_usage_db.scalar(select(DailyPromptUsage))
    assert usage is not None
    assert usage.prompt_count == 20


def test_embedding_allowance_is_account_scoped_and_resets_at_utc_midnight(
    prompt_usage_db: Session, monkeypatch
):
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: Settings(jwt_secret="test-secret", daily_embedding_token_limit=100),
    )
    user = User(email="reader@example.com", name="Reader", password_hash="hashed")
    other_user = User(email="other@example.com", name="Other", password_hash="hashed")
    prompt_usage_db.add_all([user, other_user])
    prompt_usage_db.commit()
    now = datetime(2026, 11, 21, 23, 59, tzinfo=timezone.utc)

    assert rate_limit.reserve_daily_embedding_tokens(prompt_usage_db, user.user_id, 65, now)
    assert not rate_limit.reserve_daily_embedding_tokens(prompt_usage_db, user.user_id, 36, now)
    assert rate_limit.get_daily_embedding_token_count(prompt_usage_db, user.user_id, now) == 65
    assert rate_limit.reserve_daily_embedding_tokens(prompt_usage_db, other_user.user_id, 100, now)
    assert rate_limit.get_daily_embedding_token_count(
        prompt_usage_db,
        user.user_id,
        now + timedelta(minutes=2),
    ) == 0


def test_usage_endpoint_reports_prompt_and_embedding_allowances(
    prompt_usage_db: Session, monkeypatch
):
    settings = Settings(jwt_secret="test-secret", daily_embedding_token_limit=100)
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    monkeypatch.setattr(usage_router, "get_settings", lambda: settings)
    user = User(email="usage@example.com", name="Reader", password_hash="hashed")
    prompt_usage_db.add(user)
    prompt_usage_db.commit()
    now = datetime.now(timezone.utc)
    request = make_request("203.0.113.15")
    rate_limit.consume_daily_prompt(prompt_usage_db, request, now)
    assert rate_limit.reserve_daily_embedding_tokens(prompt_usage_db, user.user_id, 25, now)

    usage = usage_router.get_usage(request, prompt_usage_db, user)

    assert usage.assistant_prompts_used == 1
    assert usage.assistant_prompts_remaining == 19
    assert usage.embedding_tokens_used == 25
    assert usage.embedding_tokens_remaining == 75
    assert usage.resets_at.hour == 0
    assert usage.resets_at.minute == 0


def test_auth_rate_limit_blocks_sixth_attempt_and_stores_only_hashed_keys(
    prompt_usage_db: Session, monkeypatch
):
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: Settings(jwt_secret="test-secret"),
    )
    request = make_request("203.0.113.15")
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)

    for _ in range(5):
        rate_limit.consume_auth_attempt(
            prompt_usage_db,
            request,
            "researcher@example.com",
            now,
        )

    with pytest.raises(HTTPException) as error:
        rate_limit.consume_auth_attempt(
            prompt_usage_db,
            request,
            "researcher@example.com",
            now,
        )

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == str(rate_limit.AUTH_WINDOW_SECONDS)
    rows = prompt_usage_db.scalars(select(AuthRateLimit)).all()
    assert len(rows) == 2
    assert all(len(row.key_hash) == 64 for row in rows)
    assert all("researcher@example.com" not in row.key_hash for row in rows)


def test_auth_rate_limit_resets_after_successful_login(
    prompt_usage_db: Session, monkeypatch
):
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: Settings(jwt_secret="test-secret"),
    )
    request = make_request("203.0.113.15")
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    rate_limit.consume_auth_attempt(
        prompt_usage_db,
        request,
        "researcher@example.com",
        now,
    )

    rate_limit.clear_auth_attempts(prompt_usage_db, request, "researcher@example.com")
    prompt_usage_db.commit()
    rate_limit.consume_auth_attempt(
        prompt_usage_db,
        request,
        "researcher@example.com",
        now,
    )

    rows = prompt_usage_db.scalars(select(AuthRateLimit)).all()
    assert len(rows) == 2
    assert all(row.attempt_count == 1 for row in rows)


def test_auth_rate_limit_expires_old_buckets(prompt_usage_db: Session, monkeypatch):
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: Settings(jwt_secret="test-secret"),
    )
    request = make_request("203.0.113.15")
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    rate_limit.consume_auth_attempt(
        prompt_usage_db,
        request,
        "researcher@example.com",
        now,
    )

    rate_limit.consume_auth_attempt(
        prompt_usage_db,
        request,
        "researcher@example.com",
        now + timedelta(seconds=rate_limit.AUTH_WINDOW_SECONDS),
    )

    rows = prompt_usage_db.scalars(select(AuthRateLimit)).all()
    assert len(rows) == 2
    assert all(row.attempt_count == 1 for row in rows)


def test_daily_prompt_limit_resets_at_utc_midnight_and_is_per_ip(
    prompt_usage_db: Session, monkeypatch
):
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: Settings(jwt_secret="test-secret"),
    )
    first_ip = make_request("203.0.113.15")
    other_ip = make_request("203.0.113.16")

    for _ in range(20):
        rate_limit.consume_daily_prompt(
            prompt_usage_db,
            first_ip,
            datetime(2026, 11, 21, 23, 59, tzinfo=timezone.utc),
        )

    rate_limit.consume_daily_prompt(
        prompt_usage_db,
        first_ip,
        datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc),
    )
    rate_limit.consume_daily_prompt(
        prompt_usage_db,
        other_ip,
        datetime(2026, 11, 21, 23, 59, tzinfo=timezone.utc),
    )

    assert prompt_usage_db.query(DailyPromptUsage).count() == 3


def test_draft_rejects_over_limit_before_calling_openai(monkeypatch):
    draft_answer = Mock()
    monkeypatch.setattr(assistant_router, "require_project_access", lambda *args: None)
    monkeypatch.setattr(assistant_router, "draft_answer", draft_answer)

    def reject_prompt(db, request):
        raise HTTPException(status_code=429)

    monkeypatch.setattr(assistant_router, "consume_daily_prompt", reject_prompt)

    with pytest.raises(HTTPException) as error:
        assistant_router.create_draft(
            uuid.uuid4(),
            AskRequest(question="Summarize the research"),
            make_request("203.0.113.15"),
            object(),
            object(),
            SimpleNamespace(user_id=uuid.uuid4()),
        )

    assert error.value.status_code == 429
    draft_answer.assert_not_called()
