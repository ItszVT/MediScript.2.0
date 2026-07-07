"""
medicine_info.py — assemble what a non-expert needs about a medicine, without
guessing:

  * Composition + substitutes  -> from the bundled Indian dataset (real).
  * Uses / side effects / warnings / interactions -> from openFDA, looked up on
    the actual SALT (generic), because openFDA carries generics, not Indian
    brand names. So "Glimet DS" -> salt "Metformin" -> real label info.
  * Name confirmation -> RxNorm EXACT match only (never a fuzzy guess presented
    as fact).

If a source has nothing, the field is empty and the UI says so. Network calls
are cached and fail soft. Verify live after deploy.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

try:
    import requests_cache
    _SESSION = requests_cache.CachedSession(
        "medinfo_cache", backend="sqlite", expire_after=86_400)
except Exception:
    _SESSION = requests.Session()

from app.core.config import settings
from app.services.medicine_details import details_for
from app.services.name_resolver import confirm_name

logger = logging.getLogger("mediscript.medinfo")


def _get(url: str, params: dict | None = None, timeout: int = 8) -> Any | None:
    try:
        r = _SESSION.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.info("medinfo GET failed %s: %s", url, e)
    return None


def _openfda_label(term: str) -> dict:
    """openFDA drug label for a generic/brand term."""
    params = {"search": f'openfda.generic_name:"{term}" OR openfda.brand_name:"{term}"',
              "limit": 1}
    data = _get(f"{settings.openfda_base}/drug/label.json", params)
    if not data or not data.get("results"):
        return {}
    r = data["results"][0]

    def first(field: str) -> str:
        v = r.get(field)
        return str(v[0]).strip() if isinstance(v, list) and v else ""

    return {
        "uses": first("indications_and_usage") or first("purpose"),
        "dosage": first("dosage_and_administration"),
        "warnings": first("warnings") or first("boxed_warning"),
        "side_effects": first("adverse_reactions"),
        "interactions": first("drug_interactions"),
    }


def get_medicine_info(name: str) -> dict:
    name = (name or "").strip()
    result = {
        "name": name, "composition": "", "salts": [], "substitutes": [],
        "price": None, "cheapest": None, "savings": None,
        "uses": "", "dosage": "", "warnings": "", "side_effects": "",
        "interactions": "", "rxcui": "", "verified_name": "", "sources": [],
    }
    if not name:
        return result

    # 1) local composition + price + substitutes + savings (real, from dataset)
    local = details_for(name)
    result["composition"] = local["composition"]
    result["salts"] = local["salts"]
    result["substitutes"] = local["substitutes"]
    result["price"] = local["price"]
    result["cheapest"] = local["cheapest"]
    result["savings"] = local["savings"]
    if local["composition"] or local["substitutes"]:
        result["sources"].append("India dataset")

    # 2) authoritative label info, looked up on the SALT (generic) first
    target = local["salts"][0] if local["salts"] else name
    label = _openfda_label(target)
    if not label and target != name:
        label = _openfda_label(name)
    if label:
        for k in ("uses", "dosage", "warnings", "side_effects", "interactions"):
            if label.get(k):
                result[k] = label[k]
        result["sources"].append("openFDA")

    # 3) RxNorm EXACT confirmation only (no fuzzy guess shown as fact)
    conf = confirm_name(target)
    if conf.get("confirmed"):
        result["rxcui"] = conf.get("rxcui", "")
        result["verified_name"] = conf.get("normalized", "")
        result["sources"].append("RxNorm")

    return result
