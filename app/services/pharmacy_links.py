"""Buy links = constructed searches on official pharmacy pages (not scraped,
not fabricated stock). Edit this list to change/add pharmacies."""
from __future__ import annotations

from urllib.parse import quote_plus

PHARMACIES = [
    ("Tata 1mg", "https://www.1mg.com/search/all?name={q}"),
    ("PharmEasy", "https://pharmeasy.in/search/all?name={q}"),
    ("Netmeds", "https://www.netmeds.com/catalogsearch/result/{q}/all"),
    ("Apollo Pharmacy", "https://www.apollopharmacy.in/search-medicines/{q}"),
]


def buy_links(medicine: str) -> list[dict]:
    q = quote_plus((medicine or "").strip())
    return [{"pharmacy": name, "url": tpl.format(q=q)} for name, tpl in PHARMACIES]
