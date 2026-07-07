"""
matcher.py — turn cleaned OCR candidates into medicine matches, with confidence
and diagnostics.

Design goals from the brief:
  * reduce false positives AND false negatives
  * never return an empty screen — always surface raw text, words, near matches
  * explain *why* extraction failed when it does
  * combine OCR confidence with match score into one honest confidence number

Matching strategy per candidate phrase:
  1. token_sort_ratio  (order-independent fuzzy)  — main signal
  2. partial_ratio     (substring-ish)            — catches names inside noise
  3. prefix/suffix bonus                          — "azithro" -> "azithromycin"
The database is indexed once; lookups reuse rapidfuzz's C-accelerated scorers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz, process

from . import text_processing as tp


def _windows(text: str, max_n: int = 2):
    """Yield 1..max_n word windows from a normalized phrase, plus the whole."""
    words = text.split()
    yield text
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            yield " ".join(words[i:i + n])


@dataclass
class Match:
    name: str
    score: int                 # 0-100 blended match score
    method: str                # how it was found (fuzzy / prefix / suffix)

    def as_dict(self) -> dict:
        return {"name": self.name, "score": self.score, "method": self.method}


@dataclass
class ExtractionResult:
    """Everything a caller needs — matches AND the raw context, always populated."""
    raw_text: str
    matches: list[Match] = field(default_factory=list)
    near_matches: list[Match] = field(default_factory=list)
    extracted_words: list[str] = field(default_factory=list)
    ocr_confidence: Optional[float] = None      # 0-100 from OCR.space, if present
    match_confidence: Optional[int] = None      # best match score
    confidence: Optional[int] = None            # blended overall 0-100
    diagnostics: list[str] = field(default_factory=list)
    status: str = "ok"                          # ok | partial | no_match | empty | error
    detections: list = field(default_factory=list)   # per-line: box + best + alts
    image_width: Optional[int] = None
    image_height: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "matches": [m.as_dict() for m in self.matches],
            "near_matches": [m.as_dict() for m in self.near_matches],
            "extracted_words": self.extracted_words,
            "ocr_confidence": self.ocr_confidence,
            "match_confidence": self.match_confidence,
            "confidence": self.confidence,
            "diagnostics": self.diagnostics,
            "status": self.status,
            "detections": self.detections,
            "image_width": self.image_width,
            "image_height": self.image_height,
        }


class MedicineMatcher:
    def __init__(self, medicine_names: list[str]):
        self.set_database(medicine_names)

    def set_database(self, medicine_names: list[str]) -> None:
        # keep canonical display names, index by normalized form
        self.names = [n for n in dict.fromkeys(medicine_names) if n and len(n) >= 3]
        self._norm = [tp.normalize(n) for n in self.names]
        self._by_norm = {nn: self.names[i] for i, nn in enumerate(self._norm)}

    # ------------------------------------------------------------------ core
    def strong_token_hit(self, phrase: str, min_score: int = 88,
                         min_cov: float = 0.82) -> Optional[str]:
        """Is there a medicine that matches this phrase as a WHOLE word (not a
        fragment)? Uses full-string ratio so 'university'->'univer' (cov .6) and
        'clo'->'clomid' (cov .5) are rejected, while OCR noise like
        'augrnentin'->'augmentin' (cov ~1) passes. Used by the NER filter."""
        norm = tp.normalize(phrase)
        if len(norm) < 4:
            return None
        best_name, best_ok = None, 0.0
        for window in _windows(norm, 2):
            m = process.extractOne(window, self._norm, scorer=fuzz.ratio)
            if not m:
                continue
            name, score, _ = m
            cov = min(len(window), len(name)) / max(len(window), len(name))
            if score >= min_score and cov >= min_cov and score * cov > best_ok:
                best_ok, best_name = score * cov, self._by_norm[name]
        return best_name

    def _score_candidate(self, cand: str, threshold: int, near_floor: int):
        """Return (best_matches, near_matches) dicts: norm_name -> (score, method)."""
        best: dict[str, tuple[int, str]] = {}
        near: dict[str, tuple[int, str]] = {}

        # widen recall with a few OCR-confusion spellings of the candidate
        probes = [cand] + tp.spelling_variants(cand)
        for probe in probes:
            for norm_name, score, idx in process.extract(
                    probe, self._norm, scorer=fuzz.token_sort_ratio, limit=5):
                method = "fuzzy"
                lp, ln = len(probe), len(norm_name)
                cov = min(lp, ln) / max(lp, ln) if max(lp, ln) else 0

                if norm_name == probe:
                    score, method = 100, "exact"
                elif norm_name.startswith(probe):
                    # probe is a leading abbreviation of the medicine
                    # ("azithro" -> "azithromycin"): trust only if long enough
                    if lp >= 4:
                        score = min(100, score + 8); method = "prefix"
                    else:
                        score = int(score * 0.6)
                elif probe.startswith(norm_name):
                    # the medicine name is only a PREFIX of a longer real word
                    # ("university" contains "univer"). Reward only when the
                    # lengths are close; otherwise it's a coincidental fragment.
                    if cov >= 0.8:
                        score = min(100, score + 3)
                    else:
                        score = int(score * cov); method = "weak-substr"
                elif norm_name.endswith(probe) or probe.endswith(norm_name):
                    if cov >= 0.6:
                        score = min(100, score + 4); method = "suffix"
                    else:
                        score = int(score * cov)

                # a big length mismatch means the medicine sits inside a longer
                # word — not a real hit. And sub-4-char probes are too short to
                # trust unless they matched exactly (handled above).
                if cov < 0.55:
                    score = int(score * cov)
                if lp < 4:
                    score = min(score, 62)

                score = int(score)
                if score >= threshold:
                    if score > best.get(norm_name, (0, ""))[0]:
                        best[norm_name] = (score, method)
                elif score >= near_floor:
                    if score > near.get(norm_name, (0, ""))[0]:
                        near[norm_name] = (score, method)
        return best, near

    def match_text(self, raw_text: str, threshold: int = 72,
                   ocr_confidence: Optional[float] = None,
                   image_meta: Optional[dict] = None) -> ExtractionResult:
        """Match a whole OCR blob (a line, region, or full page) to medicines."""
        res = ExtractionResult(raw_text=(raw_text or "").strip(),
                               ocr_confidence=ocr_confidence)
        res.extracted_words = tp.extract_display_words(raw_text)

        if not res.raw_text:
            res.status = "empty"
            res.diagnostics = self._diagnose(res, threshold, image_meta)
            return res

        near_floor = max(45, threshold - 22)
        best: dict[str, tuple[int, str]] = {}
        near: dict[str, tuple[int, str]] = {}
        for phrase in tp.candidate_phrases(raw_text):
            b, n = self._score_candidate(phrase, threshold, near_floor)
            for k, v in b.items():
                if v[0] > best.get(k, (0, ""))[0]:
                    best[k] = v
            for k, v in n.items():
                if k not in best and v[0] > near.get(k, (0, ""))[0]:
                    near[k] = v

        res.matches = self._to_matches(best)
        res.near_matches = self._to_matches(near)[:6]
        res.match_confidence = res.matches[0].score if res.matches else None
        res.confidence = self._blend_confidence(res)
        res.status = ("ok" if res.matches
                      else "no_match" if res.raw_text else "empty")
        res.diagnostics = self._diagnose(res, threshold, image_meta)
        return res

    def _to_matches(self, d: dict[str, tuple[int, str]]) -> list[Match]:
        out = [Match(self._by_norm[k], v[0], v[1]) for k, v in d.items()]
        out.sort(key=lambda m: m.score, reverse=True)
        return out[:10]

    # ---------------------------------------------------------- confidence
    @staticmethod
    def _blend_confidence(res: ExtractionResult) -> Optional[int]:
        """Blend OCR word confidence with match score into one 0-100 number.
        If OCR confidence is missing (Engine 3 overlay off), use match score."""
        if res.match_confidence is None:
            return None
        if res.ocr_confidence is None:
            return int(res.match_confidence)
        # weighted: match score dominates (it already implies legibility),
        # OCR confidence tempers it.
        return int(round(0.7 * res.match_confidence + 0.3 * res.ocr_confidence))

    # ----------------------------------------------------------- diagnostics
    @staticmethod
    def _diagnose(res: ExtractionResult, threshold: int,
                  image_meta: Optional[dict]) -> list[str]:
        """Human-readable reasons — never let the user face an empty screen."""
        d: list[str] = []
        meta = image_meta or {}
        w, h = meta.get("width", 0), meta.get("height", 0)
        low_ocr = res.ocr_confidence is not None and res.ocr_confidence < 55

        if res.status == "empty":
            d.append("No text was extracted from this image or region.")
            if w and h and (w < 700 or h < 700):
                d.append(f"Low resolution ({w}\u00d7{h}px). Aim for ~1000px+ on the "
                         "long edge (about 300 DPI).")
            d.append("Likely causes: heavy cursive, low contrast, glare/shadow, "
                     "a skewed angle, or an out-of-focus photo.")
            return d

        if low_ocr:
            d.append(f"OCR confidence is low ({res.ocr_confidence:.0f}%). The "
                     "handwriting was hard to read — a sharper, flatter, "
                     "higher-contrast image will help.")

        if res.status == "no_match":
            d.append(f"Text was read but nothing matched a medicine at "
                     f"\u2265{threshold}%. The extracted words are shown so you can "
                     "confirm manually.")
            if res.near_matches:
                d.append("There are near matches just below the threshold — check "
                         "whether one is correct.")
            if len(res.raw_text.replace(" ", "")) < 12:
                d.append("Only a small fragment was read — the printed header may "
                         "have been caught but the handwriting missed.")
            d.append("The medicine may also simply not be in the database yet.")
        elif res.status == "ok" and res.match_confidence is not None \
                and res.match_confidence < 85:
            d.append("Matched, but with moderate confidence — please verify the "
                     "name before relying on it.")
        return d


def merge_results(results: list[ExtractionResult]) -> ExtractionResult:
    """Combine per-line results (full-page OCR) into one page-level result."""
    page = ExtractionResult(raw_text="\n".join(r.raw_text for r in results if r.raw_text))
    seen: set[str] = set()
    for r in results:
        for m in r.matches:
            if m.name.lower() not in seen:
                seen.add(m.name.lower())
                page.matches.append(m)
        for w in r.extracted_words:
            if w not in page.extracted_words:
                page.extracted_words.append(w)
    page.matches.sort(key=lambda m: m.score, reverse=True)
    confs = [r.ocr_confidence for r in results if r.ocr_confidence is not None]
    page.ocr_confidence = round(sum(confs) / len(confs), 1) if confs else None
    page.match_confidence = page.matches[0].score if page.matches else None
    page.confidence = MedicineMatcher._blend_confidence(page)
    page.status = "ok" if page.matches else ("no_match" if page.raw_text else "empty")
    return page
