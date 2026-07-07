"""Authentication endpoints: register, login (cookie + token), logout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import COOKIE_NAME
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas import LoginIn, RegisterIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _issue_cookie(response: Response, user: User) -> str:
    token = create_access_token(subject=user.email, role=user.role)
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax",
        secure=False,  # set True behind HTTPS in production
        max_age=60 * 60 * 24 * 7, path="/",
    )
    return token


@router.post("/register")
def register(data: RegisterIn, response: Response, db: Session = Depends(get_db)):
    if data.role not in ("user", "chemist"):
        raise HTTPException(422, "role must be 'user' or 'chemist'")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = User(
        email=str(data.email), full_name=data.full_name,
        hashed_password=hash_password(data.password), role=data.role,
        pharmacy_name=data.pharmacy_name if data.role == "chemist" else "",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = _issue_cookie(response, user)
    return {"success": True, "role": user.role, "access_token": token,
            "redirect": "/chemist" if user.role == "chemist" else "/app"}


@router.post("/login")
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    token = _issue_cookie(response, user)
    return {"success": True, "role": user.role, "access_token": token,
            "redirect": "/chemist" if user.role == "chemist" else "/app"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"success": True, "redirect": "/"}
