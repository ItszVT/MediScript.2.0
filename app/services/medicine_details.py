"""
medicine_details.py — composition, price, and SUBSTITUTES WITH SAVINGS from the
bundled Indian dataset (brand_details.csv.gz).

The standout bit: for any brand we can list same-composition alternatives sorted
by price and compute how much a patient could save by switching to the cheapest
equivalent. Real prices from the dataset; nothing fabricated.
"""
from __future__ import annotations

import csv
import gzip
import logging
from pathlib import Path

logger = logging.getLogger("mediscript.details")

_BRANDS: dict[str, dict] = {}          # brand_lower -> {brand, price, composition, salts}
_BY_SALT: dict[str, list[str]] = {}    # salt_key -> [brand_lower]
_LOADED = False


def _salt_key(salts) -> str:
    return "|".join(sorted(s.lower().strip() for s in salts if s.strip()))


def _load():
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    path = Path(__file__).resolve().parents[2] / "data" / "brand_details.csv.gz"
    if not path.exists():
        logger.info("brand_details.csv.gz not found; details disabled.")
        return
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                brand = (row.get("brand") or "").strip()
                if not brand:
                    continue
                try:
                    price = float(row["price"]) if row.get("price") else None
                except (ValueError, TypeError):
                    price = None
                salts = [s for s in (row.get("salts") or "").split("|") if s]
                _BRANDS[brand.lower()] = {"brand": brand, "price": price,
                                          "composition": (row.get("composition") or "").strip(),
                                          "salts": salts}
                if salts:
                    _BY_SALT.setdefault(_salt_key(salts), []).append(brand.lower())
        logger.info("Loaded details for %d brands (%d salt groups)",
                    len(_BRANDS), len(_BY_SALT))
    except Exception as e:
        logger.warning("Failed to load brand_details: %s", e)


def details_for(name: str, max_substitutes: int = 10) -> dict:
    """Return composition, price, salts, substitutes (cheapest first with price),
    and potential savings vs the cheapest same-composition brand."""
    _load()
    rec = _BRANDS.get((name or "").strip().lower())
    if not rec:
        return {"composition": "", "price": None, "salts": [],
                "substitutes": [], "cheapest": None, "savings": None}

    subs = []
    if rec["salts"]:
        for bl in _BY_SALT.get(_salt_key(rec["salts"]), []):
            if bl == rec["brand"].lower():
                continue
            o = _BRANDS[bl]
            subs.append({"name": o["brand"], "price": o["price"]})
    # sort: priced ascending first, then unpriced
    subs.sort(key=lambda s: (s["price"] is None, s["price"] if s["price"] is not None else 1e9))
    subs = subs[:max_substitutes]

    cheapest, savings = None, None
    priced = [s for s in subs if s["price"] is not None]
    if rec["price"] and priced and priced[0]["price"] < rec["price"]:
        cheapest = priced[0]
        savings = {"amount": round(rec["price"] - cheapest["price"], 2),
                   "percent": round(100 * (rec["price"] - cheapest["price"]) / rec["price"])}

    return {"composition": rec["composition"], "price": rec["price"],
            "salts": rec["salts"], "substitutes": subs,
            "cheapest": cheapest, "savings": savings}
