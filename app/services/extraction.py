"""
extraction.py — high-level prescription extraction used by both portals.

Holds process-wide singletons (the OCR engine and the matcher over the master
medicine DB), runs the OCR.space Engine 3 pipeline, and persists prescriptions
+ detections. Returns the rich ExtractionResult (matches + raw + diagnostics).
"""
from __future__ import annotations

import logging

import cv2
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.prescription import Detection, Prescription
from app.services.drug_ner import is_medicine_line, ner_drug_terms, line_has_ner_drug
from app.services.matcher import ExtractionResult, MedicineMatcher, merge_results
from app.services.medicine_db import load_medicine_names
from app.services.ocr_service import OcrSpaceEngine3

logger = logging.getLogger("mediscript.extraction")

# --- singletons (built once) ----------------------------------------------
_MATCHER: MedicineMatcher | None = None
_ENGINE: OcrSpaceEngine3 | None = None


def get_matcher() -> MedicineMatcher:
    global _MATCHER
    if _MATCHER is None:
        names = load_medicine_names(settings.medicine_csv)
        _MATCHER = MedicineMatcher(names)
        logger.info("Matcher ready with %d medicines", len(names))
    return _MATCHER


def get_engine() -> OcrSpaceEngine3:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = OcrSpaceEngine3(api_keys=settings.ocr_keys_list,
                                  timeout=settings.ocr_timeout)
    return _ENGINE


# --- helpers ---------------------------------------------------------------
def _decode(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def process_prescription(image_bytes: bytes) -> ExtractionResult:
    """Full-page OCR (Engine 3) + per-line matching -> merged page result."""
    img = _decode(image_bytes)
    if img is None:
        r = ExtractionResult(raw_text="")
        r.status = "empty"
        r.diagnostics = ["The uploaded file could not be read as an image."]
        return r

    ocr = get_engine().read_image(img, overlay=True)
    matcher = get_matcher()
    h, w = img.shape[:2]
    meta = {"width": w, "height": h}

    if not ocr.ok:
        r = ExtractionResult(raw_text="")
        r.status = "empty"
        r.diagnostics = [ocr.error or "OCR returned no result."]
        return r

    # STEP 1: decide which lines are actually medicines (NER-style), so the
    # letterhead / patient / vitals never reach the matcher.
    ner_terms = ner_drug_terms(ocr.text)      # empty unless a model is configured
    detections = []
    kept_matches = []
    seen = set()
    for ln in ocr.lines:
        strong = matcher.strong_token_hit(ln.text)
        ner_hit = line_has_ner_drug(ln.text, ner_terms)
        is_med, reason = is_medicine_line(ln.text, bool(strong), ner_hit)
        if not is_med:
            continue
        # STEP 2: match only the medicine lines
        res = matcher.match_text(ln.text, ocr_confidence=ln.confidence,
                                 image_meta=meta)
        cands = list(res.matches) + list(res.near_matches)
        if not cands:
            continue
        best = cands[0]
        key = best.name.lower()
        if key in seen:
            continue
        seen.add(key)
        status = "ok" if best.score >= 82 else "unsure"
        x, y, bw, bh = ln.box
        detections.append({
            "line_text": ln.text,
            "box": {"x": x, "y": y, "w": bw, "h": bh},
            "best": best.as_dict(),
            "alternatives": [m.as_dict() for m in cands[1:4]],
            "status": status,
            "reason": reason,
        })
        if best.score >= 82:
            kept_matches.append(best)

    page = ExtractionResult(raw_text=ocr.text, ocr_confidence=ocr.mean_confidence)
    page.matches = sorted(kept_matches, key=lambda m: m.score, reverse=True)
    page.match_confidence = page.matches[0].score if page.matches else None
    page.confidence = page.match_confidence
    page.status = "ok" if detections else "no_match"
    if not detections:
        page.diagnostics = [
            "No medicine lines were confidently detected. The handwriting may be "
            "hard to read, or the medicines aren't in the database yet.",
            "Tip: use 'Select a region' and draw a box around one medicine name."]
    page.detections = detections
    page.image_width, page.image_height = w, h
    return page


def process_region(image_bytes: bytes, box: dict) -> ExtractionResult:
    """OCR just a user-drawn box, then match. box: {x,y,width,height} in px,
    or normalized {x1,y1,x2,y2} in 0..1."""
    img = _decode(image_bytes)
    if img is None:
        r = ExtractionResult(raw_text="")
        r.status = "empty"
        r.diagnostics = ["The uploaded file could not be read as an image."]
        return r

    h, w = img.shape[:2]
    if all(k in box for k in ("x1", "y1", "x2", "y2")) and \
            max(box["x1"], box["y1"], box["x2"], box["y2"]) <= 1.0:
        x1, y1, x2, y2 = (int(box["x1"] * w), int(box["y1"] * h),
                          int(box["x2"] * w), int(box["y2"] * h))
    else:
        x1, y1 = int(box.get("x", 0)), int(box.get("y", 0))
        x2, y2 = x1 + int(box.get("width", 0)), y1 + int(box.get("height", 0))
    x1, x2 = sorted((max(0, min(x1, w)), max(0, min(x2, w))))
    y1, y2 = sorted((max(0, min(y1, h)), max(0, min(y2, h))))

    matcher = get_matcher()
    if x2 - x1 < 3 or y2 - y1 < 3:
        return matcher.match_text("", image_meta={"width": w, "height": h})

    roi = img[y1:y2, x1:x2]
    ocr = get_engine().read_region(roi)
    return matcher.match_text(ocr.text if ocr.ok else "",
                              ocr_confidence=ocr.mean_confidence,
                              image_meta={"width": x2 - x1, "height": y2 - y1})


def classify_region(result: ExtractionResult) -> dict:
    """Turn a region's raw extraction into an honest, user-facing verdict.

    A prescription is full of non-medicine text (letterhead, patient name,
    vitals). When the user boxes a specific area we still guard against forcing
    a match: we require a strong score to call it confident, flag weak ones, and
    say plainly when the text is blank/blurry or doesn't look like a medicine.
    """
    text = (result.raw_text or "").strip()
    cands = list(result.matches) + list(result.near_matches)
    best = cands[0] if cands else None

    # nothing readable in the box
    if len(text) < 3 or not any(c.isalpha() for c in text):
        return {"status": "no_text", "readable": False, "raw_text": text,
                "best": None, "alternatives": [],
                "message": "This area looks blank or too blurry to read. "
                           "Try a tighter box around just the medicine name, "
                           "or upload a sharper, well-lit photo."}

    if best and best.score >= 82:
        return {"status": "ok", "readable": True, "raw_text": text,
                "best": best.as_dict(),
                "alternatives": [m.as_dict() for m in cands[1:4]],
                "message": ""}

    if best and best.score >= 68:
        return {"status": "unsure", "readable": True, "raw_text": text,
                "best": best.as_dict(),
                "alternatives": [m.as_dict() for m in cands[1:5]],
                "message": "Low confidence — please confirm this is the right "
                           "medicine, or pick another option below."}

    # readable text, but nothing matches a medicine well
    return {"status": "no_match", "readable": True, "raw_text": text,
            "best": None,
            "alternatives": [m.as_dict() for m in cands[:4]],
            "message": "Couldn't confidently identify a medicine here. The "
                       "handwriting may be hard to read — try a tighter box "
                       "around one medicine name, or type it in Search."}


def save_prescription(db: Session, owner_id: int,
                      result: ExtractionResult) -> Prescription:
    """Persist a scan + its matched detections."""
    presc = Prescription(owner_id=owner_id, raw_text=result.raw_text,
                         ocr_confidence=result.ocr_confidence, status=result.status)
    db.add(presc)
    db.flush()
    for m in result.matches:
        db.add(Detection(prescription_id=presc.id, line_text=result.raw_text[:500],
                         matched_name=m.name, confidence=m.score))
    db.commit()
    db.refresh(presc)
    return presc
