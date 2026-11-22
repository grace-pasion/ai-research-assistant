import hashlib
import hmac
import ipaddress
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DailyPromptUsage

DAILY_PROMPT_LIMIT = 20


def _client_ip(request: Request) -> str:
    if request.client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not determine the client IP for daily usage limits.",
        )
    try:
        return ipaddress.ip_address(request.client.host).compressed
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not determine the client IP for daily usage limits.",
        ) from None


def _client_hash(client_ip: str) -> str:
    secret = get_settings().jwt_secret.get_secret_value().encode("utf-8")
    return hmac.new(secret, client_ip.encode("utf-8"), hashlib.sha256).hexdigest()


def consume_daily_prompt(
    db: Session,
    request: Request,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    usage_date = now.astimezone(timezone.utc).date()
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        insert = postgresql_insert
    elif dialect == "sqlite":
        insert = sqlite_insert
    else:
        raise RuntimeError(f"Daily prompt limits do not support the {dialect} database dialect.")

    statement = insert(DailyPromptUsage).values(
        client_hash=_client_hash(_client_ip(request)),
        usage_date=usage_date,
        prompt_count=1,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[DailyPromptUsage.client_hash, DailyPromptUsage.usage_date],
        set_={"prompt_count": DailyPromptUsage.prompt_count + 1},
        where=DailyPromptUsage.prompt_count < DAILY_PROMPT_LIMIT,
    ).returning(DailyPromptUsage.prompt_count)

    prompt_count = db.execute(statement).scalar_one_or_none()
    db.commit()
    if prompt_count is None:
        next_reset = datetime.combine(
            usage_date + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        retry_after = max(1, int((next_reset - now.astimezone(timezone.utc)).total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily AI prompt limit reached (20 prompts per IP address). Try again after 00:00 UTC.",
            headers={"Retry-After": str(retry_after)},
        )
