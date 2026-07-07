"""
text_processing.py — everything that happens to OCR text *before* matching.

The OCR step (OCR.space Engine 3) is fixed and untouched. This module turns its
raw, noisy output into clean medicine-name candidates: it strips dosage forms,
units, frequencies and routes, expands common prescription abbreviations,
removes bracketed noise, and generates spelling variants for the handful of
character confusions OCR reliably makes on handwriting.

No data is fabricated here — these are standard pharmacology abbreviations and
well-known OCR confusion pairs, encoded as lookup tables.
"""
from __future__ import annotations

import re
from typing import Iterable

# --- token classes we want to strip from a line before it becomes a candidate -
# Dosage forms (as standalone tokens; we keep them only for line context).
DOSAGE_FORMS = {
    "tab", "tabs", "tablet", "tablets", "cap", "caps", "capsule", "capsules",
    "syp", "syr", "syrup", "susp", "suspension", "inj", "injection", "amp",
    "ampoule", "vial", "oint", "ointment", "cream", "gel", "lotion", "drop",
    "drops", "soln", "solution", "sachet", "sachets", "powder", "spray",
    "inhaler", "patch", "suppository", "pessary", "paint",
}

# Units / measurements.
UNITS = {
    "mg", "mcg", "g", "gm", "gms", "kg", "ml", "l", "iu", "unit", "units",
    "meq", "mmol", "%", "percent", "cc",
}

# Dosing frequency / timing / route abbreviations.
FREQUENCY = {
    "od", "bd", "bid", "tds", "tid", "qid", "qds", "hs", "sos", "stat", "prn",
    "ac", "pc", "am", "pm", "nocte", "mane", "q4h", "q6h", "q8h", "q12h", "qhs",
    "qd", "eod", "weekly", "daily", "once", "twice", "thrice", "morning",
    "afternoon", "evening", "night", "bedtime", "before", "after", "with",
    "without", "meal", "meals", "food", "empty", "stomach", "po", "iv", "im",
    "sc", "sl", "pr", "top", "topical", "oral", "external",
}

# General prescription noise words.
NOISE = {
    "rx", "sig", "disp", "adv", "advice", "advise", "x", "for", "and", "the",
    "days", "day", "week", "weeks", "month", "months", "continue", "review",
    "follow", "up", "next", "visit", "date", "name", "age", "sex", "patient",
    "dr", "doctor", "clinic", "hospital", "signature", "diagnosis", "complaint",
    "c/o", "h/o", "k/c/o", "wt", "bp", "pr", "temp", "pulse", "no", "yes", "to",
    "of", "as", "per", "each", "give", "take", "apply", "use", "then", "if",
}

STOPWORDS = DOSAGE_FORMS | UNITS | FREQUENCY | NOISE

# --- abbreviation expansion (only unambiguous, well-established ones) ----------
ABBREVIATIONS = {
    "pcm": "paracetamol",
    "para": "paracetamol",
    "amox": "amoxicillin",
    "azithro": "azithromycin",
    "cipro": "ciprofloxacin",
    "metfor": "metformin",
    "pan": "pantoprazole",
    "pan-d": "pantoprazole domperidone",
    "ors": "oral rehydration salts",
    "b-complex": "vitamin b complex",
    "bcomplex": "vitamin b complex",
    "vit": "vitamin",
    "inj": "",  # form word, drop
}

# --- OCR character confusions common on handwriting ---------------------------
# Applied to generate *extra* candidate spellings, never to overwrite the raw.
OCR_CONFUSIONS = [
    ("0", "o"), ("o", "0"),
    ("1", "l"), ("l", "1"), ("1", "i"), ("i", "1"),
    ("5", "s"), ("s", "5"),
    ("8", "b"), ("b", "8"),
    ("rn", "m"), ("m", "rn"),
    ("cl", "d"), ("vv", "w"),
    ("2", "z"), ("z", "2"),
]

_WORD_RE = re.compile(r"[a-z][a-z\-]*[a-z]|[a-z]", re.I)
_BRACKETS_RE = re.compile(r"[\(\[\{].*?[\)\]\}]")
_MULTISPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, drop bracketed noise, keep letters/spaces/hyphen, collapse."""
    if not text:
        return ""
    text = text.lower()
    text = _BRACKETS_RE.sub(" ", text)          # remove (…) [...] {...}
    text = re.sub(r"[^a-z0-9%\-\s]", " ", text)  # keep alnum, %, hyphen
    text = _MULTISPACE_RE.sub(" ", text).strip()
    return text


def is_noise_token(tok: str) -> bool:
    """True if a token is a dosage form, unit, frequency, or general noise."""
    t = tok.strip().lower().strip("-")
    if not t:
        return True
    if t in STOPWORDS:
        return True
    if t.isdigit():
        return True
    # pure dosage like "500mg", "40mg", "2.5", "5%"
    if re.fullmatch(r"\d+(\.\d+)?%?(mg|mcg|ml|g|gm|iu|meq)?", t):
        return True
    if len(t) < 2:
        return True
    return False


def clean_tokens(text: str) -> list[str]:
    """Normalized, noise-free tokens from a piece of text.

    Keeps the original token (e.g. the brand "pan-d") — abbreviation expansion
    is handled additively in candidate_phrases so both the brand and its
    generic composition become candidates.
    """
    norm = normalize(text)
    out: list[str] = []
    for tok in norm.split():
        if is_noise_token(tok):
            # a form-word like "inj" is noise, but an abbreviation like "pcm"
            # is meaningful — keep it if it's a known abbreviation
            if tok not in ABBREVIATIONS:
                continue
        out.append(tok)
    return out


def candidate_phrases(text: str, max_window: int = 3) -> list[str]:
    """Generate medicine-name candidates from one OCR line/blob.

    Produces: the full cleaned line, every 1..max_window word window over the
    cleaned tokens (preserving brand names), PLUS abbreviation expansions as
    extra candidates. De-duplicated, order-preserving. This is what makes
    "Tab. Augmentin 625mg" resolve to "augmentin" and keeps "Pan-D" as a brand
    while ALSO offering "pantoprazole domperidone".
    """
    tokens = clean_tokens(text)
    seen: set[str] = set()
    phrases: list[str] = []

    def add(p: str):
        p = p.strip()
        if len(p) >= 3 and p not in seen:
            seen.add(p)
            phrases.append(p)

    if tokens:
        add(" ".join(tokens))
    for n in range(1, max_window + 1):
        for i in range(len(tokens) - n + 1):
            add(" ".join(tokens[i:i + n]))
    # additive abbreviation expansions (keep the originals above)
    for tok in tokens:
        exp = ABBREVIATIONS.get(tok)
        if exp:
            add(exp)
    return phrases


def spelling_variants(word: str, max_variants: int = 6) -> list[str]:
    """A few OCR-confusion variants of a single token, to widen recall.

    Deliberately conservative: single-substitution variants only, capped, so we
    don't explode the candidate space or invent unrelated words.
    """
    word = word.lower()
    variants: list[str] = []
    seen = {word}
    for a, b in OCR_CONFUSIONS:
        if a in word:
            v = word.replace(a, b, 1)
            if v not in seen:
                seen.add(v)
                variants.append(v)
            if len(variants) >= max_variants:
                break
    return variants


def extract_display_words(text: str, limit: int = 40) -> list[str]:
    """Human-meaningful words to show the user when nothing matches.
    Keeps the raw casing of the original where possible."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in re.split(r"\s+", text):
        w = raw.strip().strip(".,:;()[]{}")
        key = w.lower()
        if len(w) >= 3 and not is_noise_token(key) and key not in seen:
            seen.add(key)
            out.append(w)
        if len(out) >= limit:
            break
    return out
