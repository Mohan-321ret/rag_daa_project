"""
Authentication API Router  –  Authentication Module
------------------------------------------------------
Endpoints:
  POST /api/v1/auth/register  – create an account, returns a JWT (auto-login)
  POST /api/v1/auth/login      – exchange email+password for a JWT
  POST /api/v1/auth/google     – exchange a Google ID token for a JWT
                                  (creates the account on first sign-in)
  GET  /api/v1/auth/me          – resolve the current user from a Bearer token
                                  (the frontend calls this on page load to
                                  restore/validate a session)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import (
    GoogleLoginRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.services.auth_service import (
    authenticate_user,
    bootstrap_role_for_new_account,
    create_access_token,
    get_current_user,
    get_or_create_google_user,
    hash_password,
    touch_last_login,
    verify_google_id_token,
)
from app.services.user_service import build_user_out

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _token_response(db: Session, user: User) -> TokenResponse:
    token = create_access_token(str(user.id))
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=build_user_out(db, user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = body.email.lower().strip()

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=bootstrap_role_for_new_account(db),
    )
    try:
        db.add(user)
        db.flush()
        touch_last_login(db, user)
        db.commit()
        db.refresh(user)
    except Exception as exc:
        db.rollback()
        logger.error("[Auth] Failed to create user %s: %s", email, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not create account.",
        )

    logger.info("[Auth] ✅ Registered new user: %s", email)
    return _token_response(db, user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email + password",
)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(db, body.email, body.password)
    if user is None:
        logger.warning("[Auth] ❌ Failed login attempt for %s", body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    touch_last_login(db, user)
    db.commit()
    logger.info("[Auth] ✅ Login: %s", user.email)
    return _token_response(db, user)


@router.post(
    "/google",
    response_model=TokenResponse,
    summary="Log in with a Google ID token (Google Sign-In)",
)
def google_login(body: GoogleLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Sign-In is not configured on this server.",
        )

    try:
        claims = verify_google_id_token(body.credential)
    except ValueError as exc:
        logger.warning("[Auth] ❌ Invalid Google token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google credential.",
        )
    except Exception as exc:
        # e.g. Google's certificate endpoint unreachable
        logger.error("[Auth] Google token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify Google credential. Try again.",
        )

    user = get_or_create_google_user(db, claims)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account is disabled.",
        )

    touch_last_login(db, user)
    db.commit()
    logger.info("[Auth] ✅ Google login: %s", user.email)
    return _token_response(db, user)


@router.get(
    "/me",
    response_model=UserOut,
    summary="Get the current authenticated user",
)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserOut:
    return build_user_out(db, current_user)
