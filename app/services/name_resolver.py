"""
name_resolver.py — the "universal medicine-name API" layer.

There IS a free, authoritative, universal API for drug names: the U.S. National
Library of Medicine's **RxNorm / RxNav** service (no key). It normalises drug
names and, importantly, offers *approximate* matching + spelling suggestions
across the entire RxNorm vocabulary:

  * /approximateTerm.json?term=<t>  — fuzzy match to real RxNorm concepts
  * /spellingsuggestions.json?name=<t> — spelling suggestions

This is authoritative for **generic names and US brands**. It does NOT contain
most **Indian brand** names (Dolo, Crocin, Combiflam, …) — for those the bundled
Indian datasets are the right source. So the app uses a layered strategy:

  1. Local fuzzy search over the merged datasets (fast, offline, covers Indian
     brands) — always shown, with similarity scores so the user picks.
  2. Optional RxNorm confirmation for the chosen/generic name — gives an
     authoritative RxCUI + normalised name when available, so we never present a
     fabricated identity. If RxNorm has nothing, we say so.

Network calls are cached and fail soft (offline -> empty, never an exception),
so this is safe to call from any endpoint. Verify live after deploy.
"""
from __future__ import annotations

import logging

import requests

try:
    import requests_cache
    _SESSION = requests_cache.CachedSession(
        "rxnorm_cache", backend="sqlite", expire_after=86_400)
except Exception:
    _SESSION = requests.Session()

from app.core.config import settings

logger = logging.getLogger("mediscript.name_resolver")


def _get(url: str, params: dict, timeout: int = 6):
    try:
        r = _SESSION.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.info("RxNav GET failed %s: %s", url, e)
    return None


def rxnorm_approximate(term: str, max_entries: int = 6) -> list[dict]:
    """Fuzzy-match a term to real RxNorm concepts. Returns [] offline/unknown."""
    term = (term or "").strip()
    if not term:
        return []
    data = _get(f"{settings.rxnorm_base}/approximateTerm.json",
                {"term": term, "maxEntries": max_entries})
    if not data:
        return []
    cands = (data.get("approximateGroup") or {}).get("candidate") or []
    out, seen = [], set()
    for c in cands:
        name = c.get("name") or ""
        rxcui = c.get("rxcui") or ""
        if not name or rxcui in seen:
            continue
        seen.add(rxcui)
        out.append({"name": name, "rxcui": rxcui,
                    "score": int(float(c.get("score", 0)))})
    return out


def rxnorm_spelling(term: str) -> list[str]:
    data = _get(f"{settings.rxnorm_base}/spellingsuggestions.json", {"name": term})
    if not data:
        return []
    return ((data.get("suggestionGroup") or {})
            .get("suggestionList") or {}).get("suggestion") or []


def confirm_name(name: str) -> dict:
    """Authoritative confirmation via RxNorm — EXACT match only. Never presents
    a fuzzy/approximate guess as 'verified' (that would be unsafe for a health
    app). Empty/soft when offline or not found."""
    name = (name or "").strip()
    result = {"confirmed": False, "rxcui": "", "normalized": "", "source": ""}
    if not name:
        return result
    data = _get(f"{settings.rxnorm_base}/rxcui.json", {"name": name})
    ids = ((data or {}).get("idGroup") or {}).get("rxnormId") or []
    if ids:
        result.update(confirmed=True, rxcui=ids[0], normalized=name, source="RxNorm")
    return result
