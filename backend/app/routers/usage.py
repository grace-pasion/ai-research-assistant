from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas import AIUsageResponse
from app.security import get_current_user
from app.services.rate_limit import (
    DAILY_PROMPT_LIMIT,
    get_daily_embedding_token_count,
    get_daily_prompt_count,
)

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("", response_model=AIUsageResponse)
def get_usage(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    prompt_count = get_daily_prompt_count(db, request, now)
    embedding_tokens = get_daily_embedding_token_count(db, user.user_id, now)
    embedding_limit = get_settings().daily_embedding_token_limit
    reset_at = datetime.combine(
        now.date() + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    return AIUsageResponse(
        assistant_prompts_used=prompt_count,
        assistant_prompts_limit=DAILY_PROMPT_LIMIT,
        assistant_prompts_remaining=max(0, DAILY_PROMPT_LIMIT - prompt_count),
        embedding_tokens_used=embedding_tokens,
        embedding_tokens_limit=embedding_limit,
        embedding_tokens_remaining=max(0, embedding_limit - embedding_tokens),
        resets_at=reset_at,
    )
