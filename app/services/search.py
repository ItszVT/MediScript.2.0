"""
search.py — medicine autocomplete/search ranking (token-aware).

Goal: for health safety we never present a guess as fact. We return a ranked
list of candidates with a similarity score so the USER picks the correct one.

Ranking must respect how medicine names work: a query like "dolo 650" or
"calpol 500" has a distinctive BRAND token ("dolo"/"calpol") plus a strength
("650"/"500"). Plain fuzzy matching lets the number dominate ("AN 500",
"AMC 500" …). So we:

  1. Prefilter on the distinctive token (longest alphabetic token) — cheap and
     it also makes search fast over the ~200k index.
  2. Score each candidate: exact > full-query prefix > brand-token is the first
     word > brand-token starts a word > brand-token substring; then reward the
     presence of the other query tokens (the strength) and prefer shorter names.
  3. Fuzzy fallback (typos / no prefilter hit) using WRatio.

Returns [{"name","similarity"}], best first.
"""
from __future__ import annotations

import re
from functools import lru_cache

from rapidfuzz import fuzz, process

_SPLIT = re.compile(r"[\s\-/.,+]+")


@lru_cache(maxsize=4)
def _index(names_key: tuple[str, ...]):
    out = []
    for n in names_key:
        nl = n.lower()
        out.append((n, nl, tuple(w for w in _SPLIT.split(nl) if w)))
    return out


def search_medicines(query: str, names: list[str], limit: int = 8,
                     min_score: int = 55) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    idx = _index(tuple(names))

    tokens = [t for t in _SPLIT.split(q) if t]
    alpha = [t for t in tokens if any(c.isalpha() for c in t)]
    primary = max(alpha, key=len) if alpha else (tokens[0] if tokens else q)
    others = [t for t in tokens if t != primary]

    scored: dict[str, float] = {}
    for original, nl, words in idx:
        if primary not in nl:                 # cheap, selective prefilter
            continue
        if nl == q:
            s = 100.0
        elif nl.startswith(q):
            s = 98.0
        else:
            fw = words[0] if words else ""
            if fw == primary:
                s = 94.0
            elif fw.startswith(primary):
                s = 90.0
            elif primary in words:
                s = 86.0
            elif any(w.startswith(primary) for w in words):
                s = 84.0
            else:
                s = 74.0                       # primary only inside a word
            for t in others:                   # reward/penalise the strength etc.
                if t in words or any(w.startswith(t) for w in words):
                    s += 4
                elif t in nl:
                    s += 2
                else:
                    s -= 7
            s -= min(len(nl) - len(q), 30) // 6  # prefer concise names
        if s > scored.get(original, 0):
            scored[original] = s

    ranked = sorted(scored.items(),
                    key=lambda kv: (-kv[1], len(kv[0]), kv[0].lower()))
    out = [{"name": n, "similarity": int(min(100, max(0, s)))}
           for n, s in ranked if s >= min_score][:limit]

    if len(out) < 3:                           # typo / no-prefix fallback
        have = {o["name"].lower() for o in out}
        # match on the distinctive brand token so a missing medicine scores low
        # and honestly (rather than a stray strength number inflating the score)
        term = primary if len(primary) >= 3 else q
        for name, score, _ in process.extract(
                term, names, scorer=fuzz.WRatio, limit=limit * 4):
            if name.lower() not in have and score >= max(min_score, 60):
                out.append({"name": name, "similarity": int(score)})
                have.add(name.lower())
            if len(out) >= limit:
                break

    return out[:limit]
