from datetime import datetime, timezone
from types import SimpleNamespace
import uuid
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import Settings
from app.models import DailyPromptUsage
from app.routers import assistant as assistant_router
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
    DailyPromptUsage.__table__.create(engine)
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
    monkeypatch.setattr(assistant_router, "require_project_owner", lambda *args: None)
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
