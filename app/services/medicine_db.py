"""
medicine_db.py — load the canonical list of medicine names used for matching.

Priority order:
  1. A CSV at MEDICINE_CSV (env) — your real dataset (e.g. built from the Kaggle
     Bangladesh medicine dataset, or an RxNorm dump). Any column whose name
     contains name/medicine/drug/brand/product is used.
  2. The bundled seed list `data/medicines_seed.csv` — a modest set of real,
     commonly-prescribed generics + Indian brands, enough to run and demo.

No names are invented; the seed list is real medicine nomenclature. Swap in the
full dataset for production by setting MEDICINE_CSV.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

logger = logging.getLogger("mediscript.medicine_db")

_NAME_HINTS = ("name", "medicine", "drug", "medication", "product", "brand")


def _names_from_csv(path: str) -> list[str]:
    df = pd.read_csv(path, low_memory=False)
    cols = [c for c in df.columns if any(h in c.lower() for h in _NAME_HINTS)]
    if not cols:
        cols = [c for c in df.columns if df[c].dtype == "object"]
    names: list[str] = []
    for c in cols:
        vals = df[c].dropna().astype(str).str.strip().tolist()
        names.extend(v for v in vals if len(v) > 2 and not v.isdigit())
    return names


def load_medicine_names(csv_path: str | None = None) -> list[str]:
    csv_path = csv_path or os.getenv("MEDICINE_CSV")
    root = Path(__file__).resolve().parents[2] / "data"
    candidates = []
    if csv_path and os.path.exists(csv_path):
        candidates.append(csv_path)
    candidates.append(str(root / "medicines_master.csv"))  # built from real sources
    candidates.append(str(root / "medicines_seed.csv"))    # fallback seed

    for path in candidates:
        try:
            names = _names_from_csv(path)
            if names:
                names = list(dict.fromkeys(names))  # dedupe, keep order
                logger.info("Loaded %d medicine names from %s", len(names), path)
                return names
        except Exception as e:
            logger.warning("Could not load medicine names from %s: %s", path, e)
    logger.warning("No medicine database available; matching will return nothing.")
    return []


_SEARCH_CACHE: list[str] | None = None


def load_search_names() -> list[str]:
    """Larger index for autocomplete/search (brands + generics). Falls back to
    the matcher list if the search file isn't built yet. Cached in-process."""
    global _SEARCH_CACHE
    if _SEARCH_CACHE is not None:
        return _SEARCH_CACHE
    root = Path(__file__).resolve().parents[2] / "data"
    for path in (root / "medicines_search.csv", root / "medicines_master.csv"):
        try:
            if path.exists():
                names = list(dict.fromkeys(_names_from_csv(str(path))))
                if names:
                    logger.info("Loaded %d search names from %s", len(names), path)
                    _SEARCH_CACHE = names
                    return names
        except Exception as e:
            logger.warning("Could not load search names from %s: %s", path, e)
    _SEARCH_CACHE = load_medicine_names()
    return _SEARCH_CACHE
