"""
User Service  –  User, Domain & Access Management
--------------------------------------------------------
build_user_out() is the ONE place that assembles a UserOut response. Two of
UserOut's fields (`domains`, `status`) are not plain columns on the User
ORM row — `domains` comes from the UserDomain join table and `status` is
derived from `is_active` — so `UserOut.model_validate(user)` directly on the
ORM object would silently default them (empty domains, "active" status) for
every user, not the correct value. Every endpoint that returns a UserOut
(app/api/auth.py, app/api/users.py) must go through this helper instead of
calling `UserOut.model_validate(user)` on the bare ORM object.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.auth import UserOut
from app.services.domain_service import get_user_domains


def build_user_out(db: Session, user: User) -> UserOut:
    data = {c.key: getattr(user, c.key) for c in user.__table__.columns}
    data["domains"] = get_user_domains(db, user.id)
    data["status"] = "active" if user.is_active else "inactive"
    return UserOut.model_validate(data)
