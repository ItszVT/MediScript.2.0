"""Pydantic request/response schemas."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = ""
    role: str = "user"                 # 'user' | 'chemist'
    pharmacy_name: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ConfirmMedicineIn(BaseModel):
    medicine: str
    qty_needed: int = 1
    context: str = "upload"
    query: Optional[str] = None
    similarity: Optional[float] = None


class RegionIn(BaseModel):
    # normalized 0..1 corner box drawn by the user
    x1: float
    y1: float
    x2: float
    y2: float
    image_id: str                      # references the uploaded temp image
    prescription_id: Optional[int] = None


class VoteIn(BaseModel):
    context: str                       # upload|search
    predicted: str
    verdict: str                       # yes|no
    query: Optional[str] = None
    similarity: Optional[float] = None


class ResolveRestockIn(BaseModel):
    medicine: str


class UpdateProfileIn(BaseModel):
    full_name: Optional[str] = None
    pharmacy_name: Optional[str] = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)
