"""
inventory_service.py — chemist stock checks, demand recording, restock
requests, and CSV/Excel import. All persistent (database-backed).
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from rapidfuzz import fuzz
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.demand import DemandEvent, RestockRequest
from app.models.inventory import InventoryItem
from app.services.pharmacy_links import buy_links


def _now():
    return datetime.now(timezone.utc)


# ------------------------- demand + restock -------------------------------
def record_demand(db: Session, medicine: str, source: str = "upload") -> None:
    db.add(DemandEvent(medicine=medicine[:160], source=source))
    db.commit()


def _open_restock(db: Session, medicine: str, reason: str) -> RestockRequest:
    existing = (db.query(RestockRequest)
                .filter(func.lower(RestockRequest.medicine) == medicine.lower(),
                        RestockRequest.resolved.is_(False)).first())
    if existing:
        existing.count += 1
        existing.last_requested_at = _now()
        db.commit()
        return existing
    req = RestockRequest(medicine=medicine[:160], reason=reason, count=1)
    db.add(req)
    db.commit()
    return req


def pending_restock(db: Session) -> list[dict]:
    rows = (db.query(RestockRequest)
            .filter(RestockRequest.resolved.is_(False))
            .order_by(RestockRequest.count.desc()).all())
    return [{"medicine": r.medicine, "count": r.count, "reason": r.reason,
             "last_requested_at": r.last_requested_at.isoformat()} for r in rows]


def resolve_restock(db: Session, medicine: str) -> bool:
    rows = (db.query(RestockRequest)
            .filter(func.lower(RestockRequest.medicine) == medicine.lower(),
                    RestockRequest.resolved.is_(False)).all())
    for r in rows:
        r.resolved = True
    db.commit()
    return bool(rows)


# ------------------------- stock check ------------------------------------
def check_stock(db: Session, owner_id: int, medicine: str,
                qty_needed: int = 1, threshold: int = 85) -> dict:
    """Check a chemist's inventory for a medicine. Records demand, and files a
    restock request when out of/not stocked."""
    med = (medicine or "").strip()
    report = {
        "medicine": med, "in_stock": False, "quantity_available": 0,
        "matched_item": None, "status": "not_stocked",
        "restock_filed": False, "buy_links": buy_links(med), "message": "",
    }
    if not med:
        report["message"] = "No medicine name provided."
        return report

    record_demand(db, med, "upload")

    items = db.query(InventoryItem).filter(InventoryItem.owner_id == owner_id).all()
    best, best_score = None, 0
    for it in items:
        s = fuzz.token_sort_ratio(med.lower(), it.name.lower())
        if s > best_score:
            best, best_score = it, s

    if best and best_score >= threshold:
        report["matched_item"] = {
            "id": best.id, "name": best.name, "brand": best.brand,
            "quantity": best.quantity, "price": best.price,
            "rack_location": best.rack_location,
            "expiry_date": best.expiry_date.isoformat() if best.expiry_date else None,
            "supplier": best.supplier,
        }
        report["quantity_available"] = best.quantity
        if best.quantity >= max(1, qty_needed):
            report.update(in_stock=True, status="in_stock",
                          message=f"In stock: {best.quantity} unit(s) of {best.name}.")
        else:
            report["status"] = "out_of_stock"
            report["message"] = f"{best.name} is out of stock. Restock filed."
            _open_restock(db, med, "out_of_stock")
            report["restock_filed"] = True
    else:
        report["message"] = f"'{med}' is not in inventory. Restock filed."
        _open_restock(db, med, "not_stocked")
        report["restock_filed"] = True

    return report


# ------------------------- inventory CRUD + import ------------------------
def list_inventory(db: Session, owner_id: int) -> list[InventoryItem]:
    return (db.query(InventoryItem)
            .filter(InventoryItem.owner_id == owner_id)
            .order_by(InventoryItem.name).all())


def inventory_stats(db: Session, owner_id: int) -> dict:
    items = list_inventory(db, owner_id)
    today = _now().date()
    low = [i for i in items if 0 < i.quantity <= i.reorder_level]
    out = [i for i in items if i.quantity <= 0]
    near_expiry = [i for i in items if i.expiry_date and
                   0 <= (i.expiry_date - today).days <= 90]
    expired = [i for i in items if i.expiry_date and i.expiry_date < today]
    total_value = sum((i.price or 0) * max(i.quantity, 0) for i in items)
    return {
        "total_items": len(items),
        "low_stock": len(low),
        "out_of_stock": len(out),
        "near_expiry": len(near_expiry),
        "expired": len(expired),
        "total_units": sum(max(i.quantity, 0) for i in items),
        "total_value": round(total_value, 2),
        "in_stock": len([i for i in items if i.quantity > i.reorder_level]),
    }


def import_csv(db: Session, owner_id: int, content: bytes, is_demo: bool = False) -> int:
    """Import inventory from a CSV. Recognised columns (case-insensitive):
    medicine/name, brand, quantity, price, rack/rack_location, expiry/expiry_date,
    supplier, reorder_level. Only `name` is required."""
    text = content.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    cols = {(c or "").lower().strip(): c for c in (reader.fieldnames or [])}

    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    c_name = col("medicine", "name", "drug")
    if not c_name:
        raise ValueError("CSV needs a 'medicine' or 'name' column.")
    c_brand, c_qty, c_price = col("brand"), col("quantity", "qty"), col("price")
    c_rack, c_exp = col("rack", "rack_location", "location"), col("expiry", "expiry_date")
    c_sup, c_reorder = col("supplier"), col("reorder_level", "reorder")

    def parse_date(v):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except Exception:
                continue
        return None

    n = 0
    for row in reader:
        name = (row.get(c_name) or "").strip()
        if not name:
            continue
        item = InventoryItem(
            owner_id=owner_id, name=name[:160],
            brand=(row.get(c_brand, "") or "").strip()[:160] if c_brand else "",
            quantity=_int(row.get(c_qty)) if c_qty else 0,
            price=_float(row.get(c_price)) if c_price else None,
            rack_location=(row.get(c_rack, "") or "").strip()[:60] if c_rack else "",
            expiry_date=parse_date(row.get(c_exp, "")) if c_exp else None,
            supplier=(row.get(c_sup, "") or "").strip()[:160] if c_sup else "",
            reorder_level=_int(row.get(c_reorder)) if c_reorder else 10,
            is_demo=is_demo,
        )
        db.add(item)
        n += 1
    db.commit()
    return n


def _int(v):
    try:
        return int(float(str(v).strip()))
    except Exception:
        return 0


def _float(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None
