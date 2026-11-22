import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    ProfileUpdate,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
    verify_password_or_dummy,
)
from app.services.audit import record_activity
from app.services.rate_limit import clear_auth_attempts, consume_auth_attempt

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def _available_username(db: Session, requested: str | None, email: str) -> str:
    if requested:
        username = requested.lower()
        if db.scalar(select(User.user_id).where(User.username == username)):
            raise HTTPException(status_code=409, detail="That username is already in use.")
        return username

    base = re.sub(r"[^a-z0-9._-]", "", email.split("@", 1)[0].lower())[:24] or "researcher"
    username = base
    suffix = 1
    while db.scalar(select(User.user_id).where(User.username == username)):
        suffix_text = str(suffix)
        username = f"{base[:32 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return username


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    if db.scalar(select(User.user_id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(
        email=email,
        username=_available_username(db, payload.username, email),
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.flush()
        record_activity(db, user.user_id, "account.registered")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from None
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.user_id), user=user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    consume_auth_attempt(db, request, email)
    user = db.scalar(select(User).where(User.email == email))
    if not verify_password_or_dummy(payload.password, user.password_hash if user else None):
        raise HTTPException(
            status_code=401,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    clear_auth_attempts(db, request, email)
    record_activity(db, user.user_id, "account.login")
    db.commit()
    return TokenResponse(access_token=create_access_token(user.user_id), user=user)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/profile", response_model=UserResponse)
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Choose at least one profile setting to update.")
    if "username" in updates:
        if updates["username"] is None:
            raise HTTPException(status_code=422, detail="Username cannot be blank.")
        existing = db.scalar(
            select(User.user_id).where(
                func.lower(User.username) == updates["username"],
                User.user_id != user.user_id,
            )
        )
        if existing:
            raise HTTPException(status_code=409, detail="That username is already in use.")
    for field, value in updates.items():
        setattr(user, field, value)
    record_activity(db, user.user_id, "account.profile_updated")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That username is already in use.") from None
    db.refresh(user)
    return user


@router.post("/password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Choose a new password different from your current one.")
    user.password_hash = hash_password(payload.new_password)
    record_activity(db, user.user_id, "account.password_changed")
    db.commit()
    return {"message": "Password changed."}
