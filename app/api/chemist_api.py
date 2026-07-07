"""Chemist (pharmacy) portal API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_chemist
from app.models.inventory import InventoryItem
from app.models.prescription import Prescription, Detection
from app.models.user import User
from app.schemas import ConfirmMedicineIn, RegionIn, ResolveRestockIn
from app.services import analytics_service as A
from app.services import inventory_service as I
from app.services.extraction import (process_prescription, process_region,
                                     save_prescription, classify_region)

router = APIRouter(prefix="/api/chemist", tags=["chemist"])

_TEMP_IMAGES: dict[str, bytes] = {}


# ---------------- prescription (with inventory dispensing view) -----------
@router.post("/upload")
async def upload(file: UploadFile = File(...),
                 chemist: User = Depends(require_chemist),
                 db: Session = Depends(get_db)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    result = process_prescription(data)
    save_prescription(db, chemist.id, result)
    image_id = uuid.uuid4().hex
    _TEMP_IMAGES[image_id] = data
    if len(_TEMP_IMAGES) > 200:
        _TEMP_IMAGES.pop(next(iter(_TEMP_IMAGES)))

    # enrich each match with live inventory availability
    out = result.as_dict()
    for m in out["matches"]:
        stock = I.check_stock(db, chemist.id, m["name"])
        m["stock"] = {"status": stock["status"],
                      "quantity": stock["quantity_available"],
                      "matched_item": stock["matched_item"]}
    out["image_id"] = image_id
    return out


@router.post("/prepare-image")
async def prepare_image(file: UploadFile = File(...),
                        chemist: User = Depends(require_chemist),
                        db: Session = Depends(get_db)):
    """Store the image for region reading (no auto-matching)."""
    import cv2
    import numpy as np
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Couldn't read that image — try a PNG or JPG.")
    h, w = img.shape[:2]
    image_id = uuid.uuid4().hex
    _TEMP_IMAGES[image_id] = data
    if len(_TEMP_IMAGES) > 200:
        _TEMP_IMAGES.pop(next(iter(_TEMP_IMAGES)))
    presc = Prescription(owner_id=chemist.id, raw_text="", status="ok")
    db.add(presc)
    db.commit()
    db.refresh(presc)
    return {"image_id": image_id, "prescription_id": presc.id,
            "image_width": w, "image_height": h}


@router.post("/manual-region")
async def manual_region(data: RegionIn, chemist: User = Depends(require_chemist),
                        db: Session = Depends(get_db)):
    img = _TEMP_IMAGES.get(data.image_id)
    if not img:
        raise HTTPException(404, "Image expired — please re-upload.")
    result = process_region(img, {"x1": data.x1, "y1": data.y1,
                                   "x2": data.x2, "y2": data.y2})
    verdict = classify_region(result)
    # add live inventory availability for the identified medicine
    if verdict.get("best"):
        stock = I.check_stock(db, chemist.id, verdict["best"]["name"])
        verdict["stock"] = {"status": stock["status"],
                            "quantity": stock["quantity_available"],
                            "matched_item": stock["matched_item"]}
        if data.prescription_id:
            db.add(Detection(prescription_id=data.prescription_id,
                             line_text=verdict["raw_text"][:500],
                             matched_name=verdict["best"]["name"],
                             confidence=verdict["best"]["score"]))
            db.commit()
    return verdict


@router.post("/confirm")
def confirm(data: ConfirmMedicineIn, chemist: User = Depends(require_chemist),
            db: Session = Depends(get_db)):
    A.record_vote(db, user_id=chemist.id, context=data.context, query=data.query,
                  predicted=data.medicine, verdict="yes", similarity=data.similarity)
    stock = I.check_stock(db, chemist.id, data.medicine, data.qty_needed)
    A.record_stock(db, user_id=chemist.id, medicine=data.medicine,
                   status=stock["status"], role="chemist")
    return {"success": True, "role": "chemist", "medicine": data.medicine,
            "stock": stock}


# ---------------- inventory ------------------------------------------------
@router.get("/inventory")
def inventory(chemist: User = Depends(require_chemist), db: Session = Depends(get_db)):
    items = I.list_inventory(db, chemist.id)
    return {
        "stats": I.inventory_stats(db, chemist.id),
        "items": [{
            "id": i.id, "name": i.name, "brand": i.brand, "quantity": i.quantity,
            "price": i.price, "rack_location": i.rack_location,
            "expiry_date": i.expiry_date.isoformat() if i.expiry_date else None,
            "supplier": i.supplier, "reorder_level": i.reorder_level,
            "is_demo": i.is_demo,
        } for i in items],
    }


@router.post("/inventory")
def add_item(name: str = Form(...), brand: str = Form(""), quantity: int = Form(0),
             price: float = Form(None), rack_location: str = Form(""),
             expiry_date: str = Form(""), supplier: str = Form(""),
             reorder_level: int = Form(10),
             chemist: User = Depends(require_chemist), db: Session = Depends(get_db)):
    from datetime import datetime
    exp = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            exp = datetime.strptime(expiry_date.strip(), fmt).date(); break
        except Exception:
            continue
    item = InventoryItem(owner_id=chemist.id, name=name.strip(), brand=brand.strip(),
                         quantity=quantity, price=price, rack_location=rack_location.strip(),
                         expiry_date=exp, supplier=supplier.strip(),
                         reorder_level=reorder_level, is_demo=False)
    db.add(item); db.commit(); db.refresh(item)
    return {"success": True, "id": item.id}


@router.patch("/inventory/{item_id}")
def update_item(item_id: int, data: dict,
                chemist: User = Depends(require_chemist),
                db: Session = Depends(get_db)):
    item = db.query(InventoryItem).filter(
        InventoryItem.id == item_id, InventoryItem.owner_id == chemist.id).first()
    if not item:
        raise HTTPException(404, "Item not found.")
    # quick relative quantity change, e.g. {"delta": -1}
    if "delta" in data:
        item.quantity = max(0, item.quantity + int(data["delta"]))
    for f in ("name", "brand", "supplier", "rack_location"):
        if f in data and data[f] is not None:
            setattr(item, f, str(data[f]).strip())
    for f in ("quantity", "reorder_level"):
        if f in data and data[f] is not None:
            setattr(item, f, max(0, int(data[f])))
    if "price" in data:
        try:
            item.price = float(data["price"]) if data["price"] not in (None, "") else None
        except (ValueError, TypeError):
            pass
    if "expiry_date" in data:
        from datetime import datetime
        exp = None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                exp = datetime.strptime(str(data["expiry_date"]).strip(), fmt).date(); break
            except Exception:
                continue
        item.expiry_date = exp
    db.commit()
    return {"success": True, "quantity": item.quantity}


@router.delete("/inventory/{item_id}")
def delete_item(item_id: int, chemist: User = Depends(require_chemist),
                db: Session = Depends(get_db)):
    item = db.query(InventoryItem).filter(
        InventoryItem.id == item_id, InventoryItem.owner_id == chemist.id).first()
    if not item:
        raise HTTPException(404, "Item not found.")
    db.delete(item); db.commit()
    return {"success": True}


@router.post("/inventory/import")
async def import_inventory(file: UploadFile = File(...),
                           chemist: User = Depends(require_chemist),
                           db: Session = Depends(get_db)):
    data = await file.read()
    try:
        n = I.import_csv(db, chemist.id, data, is_demo=False)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"success": True, "imported": n}


@router.post("/inventory/clear-demo")
def clear_demo(chemist: User = Depends(require_chemist), db: Session = Depends(get_db)):
    n = db.query(InventoryItem).filter(
        InventoryItem.owner_id == chemist.id, InventoryItem.is_demo.is_(True)).delete()
    db.commit()
    return {"success": True, "removed": n}


# ---------------- demand + restock ----------------------------------------
@router.get("/restock")
def restock(chemist: User = Depends(require_chemist), db: Session = Depends(get_db)):
    return {"pending": I.pending_restock(db)}


@router.post("/restock/resolve")
def resolve(data: ResolveRestockIn, chemist: User = Depends(require_chemist),
            db: Session = Depends(get_db)):
    return {"resolved": I.resolve_restock(db, data.medicine)}


# ---------------- analytics ------------------------------------------------
@router.get("/analytics")
def analytics(chemist: User = Depends(require_chemist), db: Session = Depends(get_db)):
    return A.business_summary(db)


@router.get("/industry-news")
def industry_news(chemist: User = Depends(require_chemist)):
    from app.services.news_service import fetch_drug_recalls, fetch_news
    return {"news": fetch_news("pharma", limit=10),
            "recalls": fetch_drug_recalls(limit=10)}
