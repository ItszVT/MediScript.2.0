"""
build_medicine_db.py — build the medicine datasets from REAL public sources.

Produces two files:
  data/medicines_master.csv  — accurate generic/curated names (~7k) used by the
                               OCR MATCHER (kept clean for match accuracy).
  data/medicines_search.csv  — master + ~198k Indian brand names, used by the
                               autocomplete SEARCH (maximum coverage).

Sources (all real, public):
  1. data/sources/curated_india.csv     curated generics + common brands
  2. data/sources/bnf_clean.txt          cleaned Open BNF (UK) drug names
  3. data/sources/indian_generics.txt    generics from the A-Z India dataset
  4. data/sources/indian_brands.txt      brand product names from the A-Z India
                                         dataset (the Kaggle "A-Z Medicines
                                         Dataset of India", mirrored on GitHub)
  5. any --extra CSVs (e.g. your own Kaggle download)

If the Indian source lists are missing, this script fetches + rebuilds them
from the GitHub mirror automatically (needs network). Re-run any time:

    python scripts/build_medicine_db.py
    python scripts/build_medicine_db.py --extra data/sources/mine.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources"
DATASETS = ROOT / "data" / "datasets"          # drop-in user datasets
MASTER = ROOT / "data" / "medicines_master.csv"
SEARCH = ROOT / "data" / "medicines_search.csv"
DETAILS = ROOT / "data" / "brand_details.csv.gz"

INDIAN_CSV_URL = ("https://raw.githubusercontent.com/junioralive/"
                  "Indian-Medicine-Dataset/main/DATA/indian_medicine_data.csv")

_NAME_HINTS = ("name", "medicine", "drug", "medication", "product", "brand",
               "composition", "salt", "generic")
_CLEAN = re.compile(r"\s+")
_FORMS = (r"(tablet|tablets|tab|capsule|capsules|cap|syrup|suspension|susp|"
          r"injection|inj|cream|gel|ointment|lotion|drops|drop|solution|soln|"
          r"powder|sachet|spray|inhaler|respules|rotacaps|infusion|granules|"
          r"paste|oral|eye|ear|nasal|vial|kit|sr|xr|cr|od|dt|md|forte|plus|duo)")
_DOSE = re.compile(r"\b\d+(\.\d+)?\s*(mg|mcg|ml|gm|g|iu|%|units?)\b", re.I)


def _norm(s: str) -> str:
    return _CLEAN.sub(" ", str(s).strip())


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _clean_brand(name: str) -> str:
    n = _DOSE.sub(" ", name.strip())
    for _ in range(4):
        n2 = re.sub(r"\b" + _FORMS + r"\b\.?$", "", n, flags=re.I).strip(" -.,")
        if n2 == n:
            break
        n = n2
    return _CLEAN.sub(" ", n).strip(" -.,")


def _clean_generic(comp: str):
    c = re.sub(r"\(.*?\)", "", comp or "")
    c = _CLEAN.sub(" ", c).strip(" -.,")
    return c if len(c) > 2 else None


def _ensure_indian_sources():
    """Build indian_brands.txt / indian_generics.txt from the raw dataset if
    they're missing (downloading the raw CSV if necessary)."""
    brands_f = SOURCES / "indian_brands.txt"
    generics_f = SOURCES / "indian_generics.txt"
    if brands_f.exists() and generics_f.exists():
        return
    raw = SOURCES / "indian_medicine_data.csv"
    if not raw.exists():
        print("Fetching Indian medicine dataset (~32MB) from GitHub…")
        try:
            import urllib.request
            urllib.request.urlretrieve(INDIAN_CSV_URL, raw)
        except Exception as e:
            print(f"  ! could not download ({e}); skipping Indian data.")
            return
    brands, generics = set(), set()
    with open(raw, encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            b = _clean_brand(row.get("name", ""))
            if 2 < len(b) <= 50 and re.search(r"[A-Za-z]", b):
                brands.add(b)
            for col in ("short_composition1", "short_composition2"):
                g = _clean_generic(row.get(col, ""))
                if g and re.search(r"[A-Za-z]", g) and len(g) <= 50:
                    generics.add(g)
    brands_f.write_text("\n".join(sorted(brands)), encoding="utf-8")
    generics_f.write_text("\n".join(sorted(generics)), encoding="utf-8")
    print(f"  built indian_brands.txt ({len(brands)}) + "
          f"indian_generics.txt ({len(generics)})")


def _lines(path: Path, source: str) -> list[tuple[str, str]]:
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            nm = _norm(line)
            if len(nm) > 2:
                out.append((nm, source))
    return out


def _curated() -> list[tuple[str, str]]:
    path = SOURCES / "curated_india.csv"
    out = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                nm = _norm(row.get("name", ""))
                if len(nm) > 2:
                    out.append((nm, "curated_india"))
    return out


def _extra(paths) -> list[tuple[str, str]]:
    out = []
    for p in paths or []:
        if not os.path.exists(p):
            print(f"  ! extra not found: {p}")
            continue
        out.extend(_read_any(p))
    return out


def _discover_datasets() -> list[tuple[str, str]]:
    """Auto-merge every .csv/.txt dropped into data/datasets/."""
    out = []
    if not DATASETS.exists():
        return out
    files = [f for f in DATASETS.iterdir()
             if f.suffix.lower() in (".csv", ".txt") and f.name != "README.md"]
    for f in sorted(files):
        n_before = len(out)
        out.extend(_read_any(str(f)))
        print(f"  + dataset {f.name}: +{len(out) - n_before} names")
    return out


def _read_any(path: str) -> list[tuple[str, str]]:
    """Read a CSV (name-like columns) or TXT (one name per line). Brand-style
    product names are cleaned so they match well."""
    src = os.path.splitext(os.path.basename(path))[0]
    out = []
    if path.lower().endswith(".txt"):
        for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
            nm = _norm(line)
            if 2 < len(nm) <= 80:
                out.append((nm, src))
                cb = _clean_brand(nm)
                if cb and cb.lower() != nm.lower():
                    out.append((cb, src))
        return out
    try:
        import pandas as pd
        df = pd.read_csv(path, low_memory=False)
        cols = [c for c in df.columns if any(h in c.lower() for h in _NAME_HINTS)]
        cols = cols or [c for c in df.columns if df[c].dtype == "object"]
        for c in cols:
            is_comp = "composition" in c.lower() or "salt" in c.lower()
            for v in df[c].dropna().astype(str):
                nm = _norm(v)
                if not (2 < len(nm) <= 80) or nm.isdigit():
                    continue
                if is_comp:
                    g = _clean_generic(nm)
                    if g:
                        out.append((g, src))
                else:
                    out.append((nm, src))
                    cb = _clean_brand(nm)
                    if cb and cb.lower() != nm.lower():
                        out.append((cb, src))
    except Exception as e:
        print(f"  ! failed to read {path}: {e}")
    return out


def _dedupe_write(rows, path: Path):
    seen: dict[str, tuple[str, str]] = {}
    for name, source in rows:
        k = _key(name)
        if k and k not in seen:
            seen[k] = (name, source)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "source"])
        for name, source in sorted(seen.values()):
            w.writerow([name, source])
    return seen


def _build_brand_details():
    """Build data/brand_details.csv.gz (brand -> composition + salts) from the
    raw India dataset, for the search 'what's in it / substitutes' feature.
    Skips if already present (it's shipped). Needs the raw CSV (auto-fetched)."""
    import gzip
    if DETAILS.exists():
        return
    raw = SOURCES / "indian_medicine_data.csv"
    if not raw.exists():
        try:
            import urllib.request
            print("Fetching India dataset for composition details…")
            urllib.request.urlretrieve(INDIAN_CSV_URL, raw)
        except Exception as e:
            print(f"  ! could not build brand_details ({e}); shipped copy used if present.")
            return
    seen = {}
    with open(raw, encoding="utf-8", errors="ignore") as f:
        for r in csv.DictReader(f):
            b = _clean_brand(r.get("name", ""))
            if not (2 < len(b) <= 50) or not re.search(r"[A-Za-z]", b):
                continue
            c1, c2 = r.get("short_composition1", "").strip(), r.get("short_composition2", "").strip()
            comp = re.sub(r"\s+", " ", " + ".join(x for x in (c1, c2) if x)).strip(" +")
            salts = [s for s in (_clean_generic(c1), _clean_generic(c2)) if s]
            try:
                price = round(float(str(r.get("price(₹)") or r.get("price") or "")
                                    .replace("₹", "").strip()), 2)
            except (ValueError, TypeError):
                price = ""
            key = b.lower()
            if key not in seen:
                seen[key] = (b, price, comp, "|".join(salts))
    with gzip.open(DETAILS, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["brand", "price", "composition", "salts"])
        for row in seen.values():
            w.writerow(row)
    print(f"brand_details.csv.gz    {len(seen):>7} brands (price + composition + substitutes)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", nargs="*", default=[])
    args = ap.parse_args()

    _ensure_indian_sources()
    _build_brand_details()

    curated = _curated()
    bnf = _lines(SOURCES / "bnf_clean.txt", "open_bnf")
    ind_generics = _lines(SOURCES / "indian_generics.txt", "india_generic")
    ind_brands = _lines(SOURCES / "indian_brands.txt", "india_brand")
    extra = _extra(args.extra)
    dropped = _discover_datasets()          # anything in data/datasets/

    # MASTER (matcher): accurate names only — curated + BNF + Indian generics
    # + your datasets. (Brands go to the search index, not the matcher.)
    master = _dedupe_write(curated + bnf + ind_generics + extra + dropped, MASTER)
    print(f"medicines_master.csv  {len(master):>7} names  (OCR matcher)")

    # SEARCH (autocomplete): everything, incl. Indian brands + your datasets
    search = _dedupe_write(
        curated + bnf + ind_generics + extra + dropped + ind_brands, SEARCH)
    print(f"medicines_search.csv  {len(search):>7} names  (search index)")


if __name__ == "__main__":
    main()
