"""
Auth Service  –  Authentication Module
------------------------------------------
Password hashing and JWT issuance/verification for the SPA's Bearer-token
login flow.

Password hashing calls the `bcrypt` package directly rather than going
through `passlib.CryptContext` (the usual FastAPI-tutorial pattern):
passlib 1.7.4's bcrypt backend-detection code is incompatible with
bcrypt>=4.1 and raises `ValueError: password cannot be longer than 72
bytes...` on the very first hash call in this environment (bcrypt 5.0.0
is installed). Calling `bcrypt.hashpw`/`bcrypt.checkpw` directly sidesteps
passlib's broken version probing entirely.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import (
    DEFAULT_ROLE,
    Permission,
    Role,
    role_has_all_permissions,
    role_has_any_permission,
)
from app.db.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: Optional[str]) -> bool:
    if not hashed:
        # Google-OAuth accounts have no local password (hashed_password is NULL).
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed/legacy hash – treat as a failed verification, not a crash.
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(subject: str) -> str:
    """Encode a JWT whose `sub` claim is the user's id (as a string)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[str]:
    """Return the `sub` claim (user id) if *token* is valid and unexpired, else None."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None


def touch_last_login(db: Session, user: User) -> None:
    """Stamp `last_login` = now. Called from register/login/google login."""
    user.last_login = datetime.now(timezone.utc)
    db.flush()


# ── RBAC bootstrap ────────────────────────────────────────────────────────────

def bootstrap_role_for_new_account(db: Session) -> str:
    """
    Role to assign a brand-new account (register OR first Google sign-in).

    The very first user this system ever sees becomes PLATFORM_OWNER — there
    would otherwise be no way for anyone to hold Permission.ROLE_ASSIGN and
    promote the rest of the org. Every account after that starts at the
    least-privileged DEFAULT_ROLE and must be explicitly promoted.
    """
    if db.query(User).count() == 0:
        logger.warning("[Auth] 👑 First account on this system — bootstrapping as PLATFORM_OWNER.")
        return Role.PLATFORM_OWNER.value
    return DEFAULT_ROLE.value


# ── Google OAuth ──────────────────────────────────────────────────────────────

def verify_google_id_token(credential: str) -> dict:
    """
    Verify a Google Identity Services ID token and return its claims.

    Checks signature (against Google's rotating public keys), expiry, issuer
    and audience (must equal GOOGLE_CLIENT_ID). Raises ValueError on any
    invalid/expired/mis-audienced token.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    claims = google_id_token.verify_oauth2_token(
        credential, google_requests.Request(), settings.google_client_id
    )
    if not claims.get("email"):
        raise ValueError("Google token has no email claim.")
    if not claims.get("email_verified", False):
        raise ValueError("Google account email is not verified.")
    return claims


def get_or_create_google_user(db: Session, claims: dict) -> User:
    """
    Resolve the User for a verified set of Google ID-token claims.

    An existing account with the same email (local or Google) is reused —
    Google has verified ownership of the address, so this is a safe link.
    Otherwise a passwordless account is created with auth_provider="google".
    """
    email = claims["email"].lower().strip()
    user = db.query(User).filter(User.email == email).first()

    if user is None:
        user = User(
            email=email,
            hashed_password=None,
            full_name=claims.get("name"),
            auth_provider="google",
            picture=claims.get("picture"),
            role=bootstrap_role_for_new_account(db),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("[Auth] ✅ Created Google account: %s", email)
        return user

    # Backfill profile data on returning/linked accounts.
    changed = False
    if not user.full_name and claims.get("name"):
        user.full_name = claims["name"]
        changed = True
    if claims.get("picture") and user.picture != claims["picture"]:
        user.picture = claims["picture"]
        changed = True
    if changed:
        db.commit()
        db.refresh(user)
    return user


# ── Authentication ────────────────────────────────────────────────────────────

def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Return the User if email+password are correct, else None."""
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency: resolves the caller's User from an
    `Authorization: Bearer <token>` header, or raises 401.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise unauthorized

    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise unauthorized

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None or not user.is_active:
        raise unauthorized
    return user


# ── RBAC enforcement ─────────────────────────────────────────────────────────
# Centralized authorization dependencies. Routers depend on THESE — never on
# `current_user.role` directly — so the permission matrix in
# app/core/permissions.py stays the single source of truth. 401 means "we
# don't know who you are"; 403 means "we know, and the answer is no".

def current_role(current_user: User = Depends(get_current_user)) -> Role:
    try:
        return Role(current_user.role)
    except ValueError:
        # Corrupt/unrecognized role string in the DB – fail closed, not open.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account role is not recognized. Contact an administrator.",
        )


def require_role(*roles: Role):
    """FastAPI dependency: caller's role must be one of *roles*."""
    allowed = set(roles)

    def dependency(
        current_user: User = Depends(get_current_user),
        role: Role = Depends(current_role),
    ) -> User:
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {', '.join(r.value for r in allowed)}.",
            )
        return current_user

    return dependency


def require_permission(*permissions: Permission, any_of: bool = False):
    """
    FastAPI dependency: caller's role must hold *permissions* (all of them
    by default; pass any_of=True to require just one). Returns the resolved
    User so handlers can use it (e.g. for ownership checks) without a second
    Depends(get_current_user) call.
    """

    def dependency(
        current_user: User = Depends(get_current_user),
        role: Role = Depends(current_role),
    ) -> User:
        ok = (
            role_has_any_permission(role, permissions)
            if any_of
            else role_has_all_permissions(role, permissions)
        )
        if not ok:
            joiner = " or " if any_of else " and "
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires permission: {joiner.join(p.value for p in permissions)}.",
            )
        return current_user

    return dependency
