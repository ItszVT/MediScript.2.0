"""
analytics_service.py — record and aggregate analytics from the DATABASE, so
figures persist across sessions and restarts (not per-session memory).

Two audiences:
  * personal (a single user): their own scans, searches, accuracy over time.
  * business (chemist / global): demand, stock fulfilment, restock frequency.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.analytics import SearchEvent, StockEvent, VoteEvent
from app.models.demand import DemandEvent, RestockRequest
from app.models.prescription import Detection, Prescription


# ----------------------------- recording ---------------------------------
def record_vote(db: Session, *, user_id, context, query, predicted,
                verdict, similarity=None):
    db.add(VoteEvent(user_id=user_id, context=context, query=(query or "")[:300],
                     predicted=(predicted or "")[:200], verdict=verdict,
                     similarity=similarity))
    db.commit()


def record_search(db: Session, *, user_id, query, top_result=""):
    db.add(SearchEvent(user_id=user_id, query=(query or "")[:200],
                       top_result=(top_result or "")[:200]))
    db.commit()


def record_stock(db: Session, *, user_id, medicine, status, role="user"):
    db.add(StockEvent(user_id=user_id, medicine=(medicine or "")[:200],
                      status=status, role=role))
    db.commit()


# ----------------------------- helpers ------------------------------------
def _acc(total, yes):
    return round(100.0 * yes / total, 1) if total else None


def _vote_counts(db: Session, *filters):
    q = db.query(
        func.count(VoteEvent.id),
        func.sum(case((VoteEvent.verdict == "yes", 1), else_=0)),
    )
    for f in filters:
        q = q.filter(f)
    total, yes = q.one()
    total, yes = total or 0, yes or 0
    return {"total": total, "yes": yes, "no": total - yes, "accuracy": _acc(total, yes)}


# ----------------------------- personal -----------------------------------
def personal_summary(db: Session, user_id: int) -> dict:
    scans = db.query(func.count(Prescription.id)).filter(
        Prescription.owner_id == user_id).scalar() or 0
    detections = (db.query(func.count(Detection.id))
                  .join(Prescription, Detection.prescription_id == Prescription.id)
                  .filter(Prescription.owner_id == user_id).scalar() or 0)
    votes = _vote_counts(db, VoteEvent.user_id == user_id)

    most_searched = [
        {"query": q, "count": c} for q, c in
        db.query(SearchEvent.query, func.count(SearchEvent.id))
          .filter(SearchEvent.user_id == user_id)
          .group_by(SearchEvent.query)
          .order_by(func.count(SearchEvent.id).desc()).limit(8).all()
    ]

    # monthly activity (last 6 months) — scans per month
    monthly = _monthly_counts(db, Prescription.created_at,
                              Prescription.owner_id == user_id)

    recent = [
        {"medicine": d.matched_name, "confidence": d.confidence,
         "text": d.line_text}
        for d in (db.query(Detection)
                  .join(Prescription, Detection.prescription_id == Prescription.id)
                  .filter(Prescription.owner_id == user_id)
                  .order_by(Detection.id.desc()).limit(10).all())
    ]

    # confidence distribution of all detections (strong/possible/weak)
    all_conf = [c for (c,) in
                db.query(Detection.confidence)
                  .join(Prescription, Detection.prescription_id == Prescription.id)
                  .filter(Prescription.owner_id == user_id).all()]
    conf_dist = {
        "strong": sum(1 for c in all_conf if c >= 85),
        "possible": sum(1 for c in all_conf if 70 <= c < 85),
        "weak": sum(1 for c in all_conf if c < 70),
    }

    # most-detected medicines (by frequency)
    top_meds = [
        {"medicine": m, "count": c} for m, c in
        db.query(Detection.matched_name, func.count(Detection.id))
          .join(Prescription, Detection.prescription_id == Prescription.id)
          .filter(Prescription.owner_id == user_id, Detection.matched_name != "")
          .group_by(Detection.matched_name)
          .order_by(func.count(Detection.id).desc()).limit(8).all()
    ]

    return {
        "prescriptions_scanned": scans,
        "medicines_detected": detections,
        "accuracy": votes,
        "most_searched": most_searched,
        "monthly_activity": monthly,
        "recent_medicines": recent,
        "confidence_distribution": conf_dist,
        "top_medicines": top_meds,
        "avg_confidence": round(sum(all_conf) / len(all_conf), 1) if all_conf else None,
    }


# ----------------------------- business/chemist ---------------------------
def business_summary(db: Session) -> dict:
    votes = _vote_counts(db)  # global prediction accuracy

    stock_rows = dict(
        db.query(StockEvent.status, func.count(StockEvent.id))
          .group_by(StockEvent.status).all())
    in_stock = stock_rows.get("in_stock", 0)
    needs = stock_rows.get("out_of_stock", 0) + stock_rows.get("not_stocked", 0)
    total_checks = in_stock + needs

    top_demand = [
        {"medicine": m, "count": c} for m, c in
        db.query(DemandEvent.medicine, func.count(DemandEvent.id))
          .group_by(DemandEvent.medicine)
          .order_by(func.count(DemandEvent.id).desc()).limit(10).all()
    ]
    top_restock = [
        {"medicine": r.medicine, "count": r.count, "reason": r.reason}
        for r in db.query(RestockRequest)
                   .filter(RestockRequest.resolved.is_(False))
                   .order_by(RestockRequest.count.desc()).limit(10).all()
    ]
    monthly_demand = _monthly_counts(db, DemandEvent.created_at)

    return {
        "accuracy": votes,
        "stock": {
            "total_checks": total_checks,
            "in_stock": in_stock,
            "needs_restock": needs,
            "fulfillment_rate": _acc(total_checks, in_stock),
            "by_status": stock_rows,
        },
        "top_demand": top_demand,
        "top_restock": top_restock,
        "monthly_demand": monthly_demand,
    }


def _monthly_counts(db: Session, ts_col, *filters, months: int = 6):
    since = datetime.now(timezone.utc) - timedelta(days=31 * months)
    q = db.query(ts_col)
    for f in filters:
        q = q.filter(f)
    q = q.filter(ts_col >= since)
    buckets: dict[str, int] = {}
    for (ts,) in q.all():
        if ts is None:
            continue
        key = ts.strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0) + 1
    return [{"month": k, "count": v} for k, v in sorted(buckets.items())]
