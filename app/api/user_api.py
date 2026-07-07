"""User (patient) portal API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.prescription import Prescription, Detection
from app.schemas import ConfirmMedicineIn, RegionIn, VoteIn
from app.services import analytics_service as A
from app.services import inventory_service as I
from app.services.extraction import process_prescription, process_region, save_prescription, classify_region
from app.services.medicine_db import load_search_names
from app.services.medicine_info import get_medicine_info
from app.services.pharmacy_links import buy_links
from app.services.search import search_medicines
from app.services.name_resolver import rxnorm_approximate

router = APIRouter(prefix="/api/user", tags=["user"])

# temp store for uploaded images so manual-region can re-OCR the same file
_TEMP_IMAGES: dict[str, bytes] = {}
_SEARCH_NAMES = load_search_names()


@router.post("/upload")
async def upload(file: UploadFile = File(...),
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    result = process_prescription(data)
    presc = save_prescription(db, user.id, result)

    image_id = uuid.uuid4().hex
    _TEMP_IMAGES[image_id] = data
    if len(_TEMP_IMAGES) > 200:                      # bound memory
        _TEMP_IMAGES.pop(next(iter(_TEMP_IMAGES)))

    out = result.as_dict()
    out.update(prescription_id=presc.id, image_id=image_id)
    return out


@router.post("/prepare-image")
async def prepare_image(file: UploadFile = File(...),
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Store the uploaded image for region reading (no auto-matching), and open
    a prescription record so region reads count toward analytics."""
    from app.services import extraction as _ext
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    img = _ext._decode(data)
    if img is None:
        raise HTTPException(400, "Couldn't read that image — try a PNG or JPG.")
    h, w = img.shape[:2]
    image_id = uuid.uuid4().hex
    _TEMP_IMAGES[image_id] = data
    if len(_TEMP_IMAGES) > 200:
        _TEMP_IMAGES.pop(next(iter(_TEMP_IMAGES)))
    presc = Prescription(owner_id=user.id, raw_text="", status="ok")
    db.add(presc)
    db.commit()
    db.refresh(presc)
    return {"image_id": image_id, "prescription_id": presc.id,
            "image_width": w, "image_height": h}


@router.post("/manual-region")
async def manual_region(data: RegionIn,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    img = _TEMP_IMAGES.get(data.image_id)
    if not img:
        raise HTTPException(404, "Image expired — please re-upload.")
    result = process_region(img, {"x1": data.x1, "y1": data.y1,
                                   "x2": data.x2, "y2": data.y2})
    verdict = classify_region(result)
    # record a detection for confident/unsure reads so analytics reflect it
    if data.prescription_id and verdict.get("best"):
        db.add(Detection(prescription_id=data.prescription_id,
                         line_text=verdict["raw_text"][:500],
                         matched_name=verdict["best"]["name"],
                         confidence=verdict["best"]["score"]))
        db.commit()
    return verdict


@router.get("/search")
def search(q: str, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    q = (q or "").strip()
    if not q:
        return {"success": False, "message": "Enter a medicine name."}
    results = search_medicines(q, _SEARCH_NAMES, limit=10, min_score=55)
    top = results[0]["name"] if results else ""
    A.record_search(db, user_id=user.id, query=q, top_result=top)
    # Authoritative cross-check via RxNorm (universal drug-name API). Empty when
    # offline or when the term is an Indian brand RxNorm doesn't carry.
    rx = rxnorm_approximate(q, max_entries=5)
    return {"success": bool(results or rx), "query": q,
            "results": results, "rxnorm": rx}


@router.get("/medicine-info")
def medicine_info(name: str, user: User = Depends(get_current_user)):
    return {"info": get_medicine_info(name), "buy_links": buy_links(name)}


@router.post("/confirm")
def confirm(data: ConfirmMedicineIn, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    A.record_vote(db, user_id=user.id, context=data.context, query=data.query,
                  predicted=data.medicine, verdict="yes", similarity=data.similarity)
    # patient view: info + where to buy. Demand is recorded so chemists see it.
    I.record_demand(db, data.medicine, data.context)
    info = get_medicine_info(data.medicine)
    return {"success": True, "role": "user", "medicine": data.medicine,
            "details": info, "buy_links": buy_links(data.medicine)}


@router.post("/vote")
def vote(data: VoteIn, user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    if data.verdict not in ("yes", "no"):
        raise HTTPException(422, "verdict must be yes or no")
    A.record_vote(db, user_id=user.id, context=data.context, query=data.query,
                  predicted=data.predicted, verdict=data.verdict,
                  similarity=data.similarity)
    return {"success": True}


@router.get("/analytics")
def analytics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return A.personal_summary(db, user.id)


@router.get("/health-news")
def health_news(user: User = Depends(get_current_user)):
    from app.services.news_service import fetch_news
    return {"news": fetch_news("health", limit=12)}
