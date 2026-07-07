"""
news_service.py — real, authoritative health/medicine news + drug recalls.

Sources are FREE and need no API key:
  * RSS feeds from WHO, U.S. NLM MedlinePlus, and FDA (health + medicine news).
  * openFDA drug ENFORCEMENT endpoint (real drug recalls) for chemists.

Why not Google Trends? There is no official free API; the common unofficial
library is rate-limited/blocked and unreliable — a poor fit for a health app
that must not show misleading data. Authoritative RSS + openFDA are reliable and
citable.

Everything is cached and fails soft: no network -> empty list, never an
exception. RSS/Atom is parsed with the standard library (no extra deps). Feed
lists are overridable via env (HEALTH_FEEDS / PHARMA_FEEDS, comma-separated).
Verify live after deploy.
"""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

_TAG = re.compile(r"<[^>]+>")


def _clean_html(s: str) -> str:
    """RSS summaries often contain HTML — strip tags and decode entities so the
    UI shows readable text, never raw markup."""
    if not s:
        return ""
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

try:
    import requests_cache
    _SESSION = requests_cache.CachedSession(
        "news_cache", backend="sqlite", expire_after=1800)  # 30 min
except Exception:
    _SESSION = requests.Session()

from app.core.config import settings

logger = logging.getLogger("mediscript.news")

# Authoritative, key-free feeds. Override with env if you like.
_DEFAULT_HEALTH = [
    "https://medlineplus.gov/feeds/news_en.xml",           # NIH / NLM
    "https://www.who.int/rss-feeds/news-english.xml",      # WHO
    "https://tools.cdc.gov/api/v2/resources/media/403372.rss",  # CDC newsroom
]
_DEFAULT_PHARMA = [
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml",
]


def _feeds(env_key: str, default: list[str]) -> list[str]:
    raw = os.getenv(env_key, "")
    return [u.strip() for u in raw.split(",") if u.strip()] or default


def _text(el, *tags):
    for t in tags:
        node = el.find(t)
        if node is not None and (node.text or "").strip():
            return node.text.strip()
        # Atom <link href="...">
        if t == "link" and node is not None and node.get("href"):
            return node.get("href")
    return ""


def _parse_feed(xml: str, source: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return items
    # strip namespaces for simpler finds
    for el in root.iter():
        el.tag = el.tag.split("}")[-1]
    entries = root.findall(".//item") or root.findall(".//entry")
    for e in entries[:12]:
        title = _clean_html(_text(e, "title"))
        link = _text(e, "link")
        date = _text(e, "pubDate", "published", "updated", "date")
        summary = _clean_html(_text(e, "description", "summary"))
        if title:
            items.append({"title": title, "url": link, "date": date,
                          "source": source, "summary": summary[:200]})
    return items


def _source_name(url: str) -> str:
    u = url.lower()
    if "who.int" in u:
        return "WHO"
    if "medlineplus" in u:
        return "MedlinePlus"
    if "cdc.gov" in u:
        return "CDC"
    if "fda.gov" in u:
        return "FDA"
    return url.split("/")[2] if "//" in url else "news"


def fetch_news(kind: str = "health", limit: int = 12) -> list[dict]:
    """kind: 'health' (patients) or 'pharma' (chemists)."""
    feeds = (_feeds("HEALTH_FEEDS", _DEFAULT_HEALTH) if kind == "health"
             else _feeds("PHARMA_FEEDS", _DEFAULT_PHARMA))
    out: list[dict] = []
    for url in feeds:
        try:
            r = _SESSION.get(url, timeout=6,
                             headers={"User-Agent": "MediScript/1.0"})
            if r.status_code == 200:
                out.extend(_parse_feed(r.text, _source_name(url)))
        except Exception as e:
            logger.info("news feed failed %s: %s", url, e)
    # de-dupe by title, keep order, cap
    seen, uniq = set(), []
    for it in out:
        k = it["title"].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq[:limit]


def fetch_drug_recalls(limit: int = 10) -> list[dict]:
    """Recent U.S. drug recalls from the openFDA enforcement API (real data)."""
    try:
        r = _SESSION.get(f"{settings.openfda_base}/drug/enforcement.json",
                         params={"search": "status:Ongoing", "limit": limit,
                                 "sort": "recall_initiation_date:desc"}, timeout=8)
        if r.status_code != 200:
            return []
        results = r.json().get("results", [])
    except Exception as e:
        logger.info("openFDA recalls failed: %s", e)
        return []
    out = []
    for x in results:
        out.append({
            "product": (x.get("product_description") or "")[:160],
            "reason": (x.get("reason_for_recall") or "")[:220],
            "company": x.get("recalling_firm", ""),
            "classification": x.get("classification", ""),
            "date": x.get("recall_initiation_date", ""),
            "status": x.get("status", ""),
        })
    return out
