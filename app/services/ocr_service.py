"""
ocr_service.py — the ONLY OCR engine: OCR.space Engine 3.

The request to OCR.space is intentionally minimal and stable. We only *read
more* out of the response than before (per-word confidence via the overlay);
we do not swap engines, add fallbacks, or change the extraction request beyond
what OCR.space documents for Engine 3.

Everything downstream (cleaning, matching, diagnostics) lives in
text_processing.py and matcher.py, never here.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
import requests

logger = logging.getLogger("mediscript.ocr")

OCR_API_URL = "https://api.ocr.space/parse/image"
FREE_TIER_BYTE_LIMIT = 1024 * 1024  # ~1 MB for the free tier


@dataclass
class OcrLine:
    text: str
    box: tuple[int, int, int, int]      # x, y, w, h in ORIGINAL image coords
    confidence: Optional[float] = None  # 0-100 mean word confidence, if present


@dataclass
class OcrResult:
    text: str = ""
    lines: list[OcrLine] = field(default_factory=list)
    mean_confidence: Optional[float] = None
    ok: bool = False
    error: Optional[str] = None
    exit_code: Optional[int] = None


class QuotaExhausted(Exception):
    """Raised when OCR.space reports the key/quota is spent."""


def _encode_jpg(image: np.ndarray, max_side: int = 1600, quality: int = 85):
    """Downscale + JPEG-encode to stay under the free-tier byte limit.
    Returns (jpg_bytes, scale) where scale = sent_px / original_px."""
    h, w = image.shape[:2]
    scale = 1.0
    if max(h, w) > max_side:
        scale = max_side / float(max(h, w))
        image = cv2.resize(image, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None, 1.0
    # if still too big, drop quality once
    if buf.nbytes > FREE_TIER_BYTE_LIMIT:
        ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
    return (buf.tobytes(), scale) if ok else (None, 1.0)


class OcrSpaceEngine3:
    """Thin, single-purpose client for OCR.space Engine 3."""

    def __init__(self, api_keys: list[str], timeout: int = 90,
                 session: Optional[requests.Session] = None):
        self.api_keys = [k.strip() for k in api_keys if k and k.strip()] or ["helloworld"]
        self.timeout = timeout
        self.session = session or requests.Session()

    # ---- public API -------------------------------------------------------
    def read_image(self, image: np.ndarray, overlay: bool = True) -> OcrResult:
        """Full-page read. overlay=True gives per-line boxes + confidence."""
        payload = _encode_jpg(image)
        return self._read(payload[0], payload[1], overlay=overlay)

    def read_region(self, region: np.ndarray) -> OcrResult:
        """Read a single cropped region (manual selection). No overlay needed."""
        payload = _encode_jpg(region)
        return self._read(payload[0], payload[1], overlay=False)

    # ---- internals --------------------------------------------------------
    def _read(self, img_bytes, scale, overlay) -> OcrResult:
        if not img_bytes:
            return OcrResult(ok=False, error="Could not encode image.")
        b64 = base64.b64encode(img_bytes).decode("utf-8")

        # The stable Engine 3 request. Do not add fallbacks or other engines.
        data = {
            "base64Image": f"data:image/jpeg;base64,{b64}",
            "language": "eng",
            "OCREngine": "3",
            "scale": "true",
            "detectOrientation": "true",
            "isTable": "false",
            "isOverlayRequired": "true" if overlay else "false",
        }

        last_err = None
        for key in self.api_keys:
            try:
                resp = self.session.post(
                    OCR_API_URL, data={**data, "apikey": key}, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = f"Network error contacting OCR.space: {e}"
                continue
            if resp.status_code in (403, 429):
                last_err = "OCR.space rate limit / key throttled."
                continue
            try:
                j = resp.json()
            except ValueError:
                last_err = f"Bad response from OCR.space (HTTP {resp.status_code})."
                continue

            msg = str(j.get("ErrorMessage", "")).lower()
            if any(w in msg for w in ("limit", "quota", "exceed")):
                last_err = "OCR.space quota exhausted for this key."
                continue
            return self._parse(j, scale)

        # every key failed the same recoverable way
        if last_err and "quota" in last_err.lower():
            raise QuotaExhausted(last_err)
        return OcrResult(ok=False, error=last_err or "OCR failed.")

    @staticmethod
    def _parse(j: dict, scale: float) -> OcrResult:
        if j.get("OCRExitCode") not in (1, 2) or not j.get("ParsedResults"):
            return OcrResult(ok=False, exit_code=j.get("OCRExitCode"),
                             error=str(j.get("ErrorMessage") or "No text parsed."))
        parsed = j["ParsedResults"][0]
        full_text = (parsed.get("ParsedText") or "").strip()
        inv = 1.0 / scale if scale else 1.0
        lines: list[OcrLine] = []
        confs: list[float] = []

        overlay = parsed.get("TextOverlay") or {}
        for ln in overlay.get("Lines", []):
            words = ln.get("Words", [])
            if not words:
                continue
            xs = [w["Left"] for w in words]
            ys = [w["Top"] for w in words]
            x2 = [w["Left"] + w["Width"] for w in words]
            y2 = [w["Top"] + w.get("Height", 0) for w in words]
            # OCR.space overlay does not always include per-word confidence;
            # when present it's 0..1, so scale to 0..100.
            wc = [w["WordConf"] * 100 for w in words if "WordConf" in w]
            line_conf = round(sum(wc) / len(wc), 1) if wc else None
            if line_conf is not None:
                confs.append(line_conf)
            box = (int(min(xs) * inv), int(min(ys) * inv),
                   int((max(x2) - min(xs)) * inv), int((max(y2) - min(ys)) * inv))
            lines.append(OcrLine(text=(ln.get("LineText") or "").strip(),
                                 box=box, confidence=line_conf))

        if not lines and full_text:
            lines = [OcrLine(text=t.strip(), box=(0, 0, 0, 0))
                     for t in full_text.splitlines() if t.strip()]

        mean_conf = round(sum(confs) / len(confs), 1) if confs else None
        return OcrResult(text=full_text, lines=lines, mean_confidence=mean_conf,
                         ok=True, exit_code=j.get("OCRExitCode"))
