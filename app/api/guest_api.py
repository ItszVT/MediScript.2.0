"""
guest_api.py — no-signin demo. A visitor gets ONE free prescription read and
ONE free medicine search (tracked by a guest cookie), then is asked to sign in.
Guest actions never write user data or persist prescriptions.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.guest import GuestUsage
from app.services.extraction import process_prescription
from app.services.medicine_db import load_search_names
from app.services.name_resolver import rxnorm_approximate
from app.services.pharmacy_links import buy_links
from app.services.search import search_medicines

router = APIRouter(prefix="/api/guest", tags=["guest"])

GUEST_COOKIE = "guest_id"
FREE_UPLOADS = 1
FREE_SEARCHES = 1

_SEARCH_NAMES = load_search_names()


def _get_usage(request: Request, response: Response,
               db: Session) -> GuestUsage:
    gid = request.cookies.get(GUEST_COOKIE)
    row = db.get(GuestUsage, gid) if gid else None
    if row is None:
        gid = uuid.uuid4().hex
        row = GuestUsage(guest_id=gid)
        db.add(row)
        db.commit()
        response.set_cookie(GUEST_COOKIE, gid, httponly=True, samesite="lax",
                            max_age=60 * 60 * 24 * 30, path="/")
    return row


@router.get("/status")
def status(request: Request, response: Response, db: Session = Depends(get_db)):
    u = _get_usage(request, response, db)
    return {"uploads_left": max(0, FREE_UPLOADS - u.uploads),
            "searches_left": max(0, FREE_SEARCHES - u.searches)}


@router.post("/upload")
async def guest_upload(request: Request, response: Response,
                       file: UploadFile = File(...), db: Session = Depends(get_db)):
    u = _get_usage(request, response, db)
    if u.uploads >= FREE_UPLOADS:
        return {"limit_reached": True,
                "message": "That's your free prescription read. "
                           "Create a free account to keep going."}
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    result = process_prescription(data)          # OCR + match, not persisted
    u.uploads += 1
    db.commit()
    out = result.as_dict()
    out["uploads_left"] = max(0, FREE_UPLOADS - u.uploads)
    out["limit_reached"] = False
    return out


@router.get("/search")
def guest_search(q: str, request: Request, response: Response,
                 db: Session = Depends(get_db)):
    u = _get_usage(request, response, db)
    if u.searches >= FREE_SEARCHES:
        return {"limit_reached": True,
                "message": "That's your free search. "
                           "Create a free account to keep searching."}
    q = (q or "").strip()
    if not q:
        return {"success": False, "message": "Enter a medicine name."}
    results = search_medicines(q, _SEARCH_NAMES, limit=10, min_score=55)
    rx = rxnorm_approximate(q, max_entries=5)
    u.searches += 1
    db.commit()
    return {"success": bool(results or rx), "query": q, "results": results,
            "rxnorm": rx, "buy_links": buy_links(results[0]["name"]) if results else [],
            "searches_left": max(0, FREE_SEARCHES - u.searches), "limit_reached": False}
