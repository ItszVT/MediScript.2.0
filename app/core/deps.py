"""FastAPI auth dependencies.

Tokens are accepted from either an httponly cookie (browser portal) or an
Authorization: Bearer header (API clients). Role guards return 403 for the
wrong portal.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User

COOKIE_NAME = "access_token"


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def get_current_user_optional(request: Request,
                              db: Session = Depends(get_db)) -> User | None:
    token = _extract_token(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = db.query(User).filter(User.email == payload.get("sub")).first()
    return user


def get_current_user(request: Request,
                     db: Session = Depends(get_db)) -> User:
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")
    return user


def require_user(user: User = Depends(get_current_user)) -> User:
    # both roles may use user-facing features; patients are role 'user'
    return user


def require_chemist(user: User = Depends(get_current_user)) -> User:
    if user.role != "chemist":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Chemist account required")
    return user
