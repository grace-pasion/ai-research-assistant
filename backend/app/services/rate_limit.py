import hashlib
import hmac
import ipaddress
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuthRateLimit, DailyPromptUsage

DAILY_PROMPT_LIMIT = 20
AUTH_IP_ATTEMPT_LIMIT = 30
AUTH_IP_EMAIL_ATTEMPT_LIMIT = 5
AUTH_WINDOW_SECONDS = 15 * 60


def _client_ip(request: Request) -> str:
    if request.client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not determine the client IP for request limits.",
        )
    try:
        return ipaddress.ip_address(request.client.host).compressed
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not determine the client IP for request limits.",
        ) from None


def _client_hash(client_ip: str) -> str:
    secret = get_settings().jwt_secret.get_secret_value().encode("utf-8")
    return hmac.new(secret, client_ip.encode("utf-8"), hashlib.sha256).hexdigest()


def _auth_bucket_hash(scope: str, value: str) -> str:
    secret = get_settings().jwt_secret.get_secret_value().encode("utf-8")
    material = f"auth:{scope}:{value}".encode("utf-8")
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def _auth_rate_keys(request: Request, email: str) -> list[tuple[str, int]]:
    client_ip = _client_ip(request)
    normalized_email = email.strip().casefold()
    return [
        (_auth_bucket_hash("ip", client_ip), AUTH_IP_ATTEMPT_LIMIT),
        (
            _auth_bucket_hash("ip-email", f"{client_ip}\0{normalized_email}"),
            AUTH_IP_EMAIL_ATTEMPT_LIMIT,
        ),
    ]


def _insert_for_dialect(db: Session):
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert
    if dialect == "sqlite":
        return sqlite_insert
    raise RuntimeError(f"Request rate limits do not support the {dialect} database dialect.")


def consume_auth_attempt(
    db: Session,
    request: Request,
    email: str,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    window_start = now - timedelta(seconds=AUTH_WINDOW_SECONDS)
    insert = _insert_for_dialect(db)
    blocked_until: list[datetime] = []

    db.execute(delete(AuthRateLimit).where(AuthRateLimit.window_started_at <= window_start))
    for key_hash, limit in _auth_rate_keys(request, email):
        expired = AuthRateLimit.window_started_at <= window_start
        statement = insert(AuthRateLimit).values(
            key_hash=key_hash,
            window_started_at=now,
            attempt_count=1,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[AuthRateLimit.key_hash],
            set_={
                "window_started_at": case(
                    (expired, now),
                    else_=AuthRateLimit.window_started_at,
                ),
                "attempt_count": case(
                    (expired, 1),
                    (AuthRateLimit.attempt_count < limit, AuthRateLimit.attempt_count + 1),
                    else_=limit + 1,
                ),
            },
        ).returning(AuthRateLimit.window_started_at, AuthRateLimit.attempt_count)
        started_at, attempt_count = db.execute(statement).one()
        if attempt_count > limit:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            blocked_until.append(started_at + timedelta(seconds=AUTH_WINDOW_SECONDS))

    db.commit()
    if blocked_until:
        retry_after = max(1, int((max(blocked_until) - now).total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Try again after the rate limit window.",
            headers={"Retry-After": str(retry_after)},
        )


def clear_auth_attempts(db: Session, request: Request, email: str) -> None:
    keys = [key_hash for key_hash, _ in _auth_rate_keys(request, email)]
    db.execute(delete(AuthRateLimit).where(AuthRateLimit.key_hash.in_(keys)))


def consume_daily_prompt(
    db: Session,
    request: Request,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    usage_date = now.astimezone(timezone.utc).date()
    insert = _insert_for_dialect(db)

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
