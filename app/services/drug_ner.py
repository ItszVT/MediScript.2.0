"""
drug_ner.py — decide WHICH lines of OCR text are actually medicines, before we
try to match them to the database.

A prescription is mostly NOT medicines: hospital letterhead, patient name, age,
UHID, vitals (BP/PR), diagnosis, advice, signature. Matching every line is what
made the letterhead ("Adichunchanagiri University") come back as "Univer". So we
first detect medicine *mentions* using the structure of a prescription:

  strong signals a line is a drug order:
    - a dosage      (500 mg, 5 %, 10 ml)
    - a frequency   (OD/BD/TDS/HS/SOS/STAT, 1-0-1, x5 days)
    - a form/route  (Tab/Cap/Syp/Inj/Drops/IV/PO ...)
    - a list/Rx lead(℞, "1.", "Tab ", "T. ")
    - a STRONG, whole-word dictionary hit (not a fragment)

  strong signal a line is NOT a drug (header/footer/vitals/patient):
    - stopwords: hospital, university, institute, medical, sciences, name, age,
      uhid, signature, diagnosis, bp, pr, advice, follow-up ...

A real medical NER model (Med7 / scispaCy) could replace this by setting
DRUG_NER_MODEL, but those are ~1GB, need network, and struggle on handwriting
OCR — this offline detector is the deployable default.
"""
from __future__ import annotations

import logging
import re

from app.core.config import settings
from . import text_processing as tp

logger = logging.getLogger("mediscript.ner")

# --------------------------------------------------------------------------
# OPTIONAL medical NER model (Med7 / scispaCy), loaded only if configured.
# When DRUG_NER_MODEL is set and the model is installed, we use its DRUG /
# CHEMICAL entities as an extra high-precision signal. Otherwise we rely purely
# on the offline heuristic below. Everything fails soft — a missing or broken
# model never breaks extraction; it just falls back to the heuristic.
# --------------------------------------------------------------------------
_NLP = None
_NLP_TRIED = False


def _get_nlp():
    global _NLP, _NLP_TRIED
    if _NLP_TRIED:
        return _NLP
    _NLP_TRIED = True
    model = (settings.drug_ner_model or "").strip()
    if not model:
        return None
    try:
        import spacy
        _NLP = spacy.load(model)
        logger.info("Medical NER model loaded: %s", model)
    except Exception as e:  # not installed / bad model / spaCy missing
        logger.warning("DRUG_NER_MODEL=%r could not load (%s). "
                       "Falling back to the built-in heuristic detector.", model, e)
        _NLP = None
    return _NLP


def ner_drug_terms(text: str) -> set[str]:
    """Normalized drug terms the NER model finds in the text ({} if no model)."""
    nlp = _get_nlp()
    if not nlp or not (text or "").strip():
        return set()
    labels = {l.strip().upper() for l in (settings.drug_ner_labels or "").split(",") if l.strip()}
    terms: set[str] = set()
    try:
        for ent in nlp(text).ents:
            if ent.label_.upper() in labels:
                n = tp.normalize(ent.text)
                if len(n) >= 3:
                    terms.add(n)
    except Exception as e:
        logger.info("NER inference failed (%s); ignoring.", e)
    return terms


def line_has_ner_drug(text: str, ner_terms: set[str]) -> bool:
    if not ner_terms:
        return False
    norm = tp.normalize(text)
    return any(t in norm for t in ner_terms)

_DOSE = re.compile(r"\d+\s*\.?\d*\s*(mg|mcg|ug|ml|g|gm|iu|%|units?)\b", re.I)
_FREQ = re.compile(
    r"\b(od|bd|tds|tid|qid|qds|hs|sos|stat|prn|nocte|mane)\b"
    r"|\b\d\s*[-/xX]\s*\d\s*[-/xX]\s*\d\b"
    r"|\bx\s*\d+\s*(day|days|wk|week|weeks|month|months|d)\b", re.I)
_FORM = re.compile(
    r"\b(tab|tabs|tablet|tablets|cap|caps|capsule|syp|syr|syrup|inj|injection"
    r"|susp|suspension|drop|drops|cream|ointment|oint|gel|lotion|sachet|sachets"
    r"|powder|spray|inhaler|respule|rotacap|infusion|iv|im|po|sc|sos)\b", re.I)
_LEAD = re.compile(r"^\s*(rx|℞|\d+\s*[\.\)]|[-*•▪]|t\.?|tab|cap|inj|syp|c\.)\s+", re.I)

# header / footer / vitals / patient — never a medicine line
_STOP = {
    "hospital", "university", "institute", "college", "medical", "sciences",
    "science", "research", "centre", "center", "clinic", "healthcare", "health",
    "name", "age", "sex", "gender", "dob", "date", "uhid", "ip", "op", "opd",
    "reg", "regn", "patient", "address", "mobile", "phone", "tel", "email",
    "signature", "sign", "doctor", "dr", "consultant", "physician", "surgeon",
    "dept", "department", "ward", "bed", "room",
    "bp", "pr", "pulse", "temp", "temperature", "weight", "wt", "height", "ht",
    "spo2", "rr", "hr", "diagnosis", "complaints", "advice", "follow", "followup",
    "review", "visit", "investigation", "investigations", "report", "reports",
    "nagar", "road", "street", "nagara", "taluk", "district", "pin", "state",
}


def _stopness(words: list[str]) -> int:
    return sum(1 for w in words if w in _STOP)


def is_medicine_line(text: str, strong_hit: bool,
                     ner_hit: bool = False) -> tuple[bool, str]:
    """Return (is_medicine, reason). strong_hit = dictionary confirms a whole
    medicine token on this line; ner_hit = a medical NER model tagged a DRUG
    here (only when a model is configured)."""
    t = (text or "").strip()
    if len(t) < 3:
        return False, "too short"
    words = [tp.normalize(w) for w in re.findall(r"[A-Za-z%]+", t)]
    words = [w for w in words if w]
    stop = _stopness(words)
    confirmed = strong_hit or ner_hit

    has_dose = bool(_DOSE.search(t))
    has_freq = bool(_FREQ.search(t))
    has_form = bool(_FORM.search(t))
    has_lead = bool(_LEAD.search(t))
    drug_cue = has_dose or has_freq or has_form or has_lead or confirmed

    # header/footer lines: stopwords and no real drug cue -> reject
    if stop and not (has_dose or has_freq or confirmed):
        return False, "header/patient/vitals text"
    # a line that is *mostly* stopwords is not a medicine
    if words and stop >= max(2, len(words) - 1) and not confirmed:
        return False, "non-medicine text"
    if not drug_cue:
        return False, "no medicine cue (no dose/form/frequency/known name)"

    reasons = [r for r, ok in (("medical NER model", ner_hit),
                               ("known medicine name", strong_hit),
                               ("dosage", has_dose), ("frequency", has_freq),
                               ("form/route", has_form), ("Rx/list marker", has_lead))
               if ok]
    return True, ", ".join(reasons) or "medicine-like"
