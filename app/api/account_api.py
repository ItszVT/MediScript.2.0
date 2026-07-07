"""Account settings — profile + password. Available to any signed-in user;
pharmacy_name only applies to chemists."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas import ChangePasswordIn, UpdateProfileIn

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "email": user.email, "full_name": user.full_name, "role": user.role,
        "pharmacy_name": user.pharmacy_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/profile")
def update_profile(data: UpdateProfileIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    if data.full_name is not None:
        user.full_name = data.full_name.strip()[:120]
    if data.pharmacy_name is not None and user.role == "chemist":
        user.pharmacy_name = data.pharmacy_name.strip()[:160]
    db.commit()
    return {"success": True, "full_name": user.full_name,
            "pharmacy_name": user.pharmacy_name}


@router.post("/password")
def change_password(data: ChangePasswordIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is incorrect.")
    user.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"success": True}
