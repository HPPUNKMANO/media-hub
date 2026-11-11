"""Journal: headlines from French newspapers' official RSS feeds, merged and cached for 10 minutes."""
from __future__ import annotations

import asyncio
import html
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx
from fastapi import APIRouter

router = APIRouter()
SOURCES = [
    ("lemonde", "Le Monde", "Actualité", "https://www.lemonde.fr/rss/une.xml"),
    ("franceinfo", "franceinfo", "Actualité", "https://www.francetvinfo.fr/titres.rss"),
    ("figaro", "Le Figaro", "Actualité", "https://www.lefigaro.fr/rss/figaro_actualites.xml"),
    ("libe", "Libération", "Actualité", "https://www.liberation.fr/arc/outboundfeeds/rss-all/?outputType=xml"),
    ("20min", "20 Minutes", "Actualité", "https://www.20minutes.fr/feeds/rss-une.xml"),
    ("parisien", "Le Parisien", "Actualité", "https://feeds.leparisien.fr/leparisien/rss"),
    ("ouestfrance", "Ouest-France", "Actualité", "https://www.ouest-france.fr/rss/une"),
    ("bfmtv", "BFMTV", "Actualité", "https://www.bfmtv.com/rss/news-24-7/"),
    ("mediapart", "Mediapart", "Enquêtes", "https://www.mediapart.fr/articles/feed"),
    ("courrier", "Courrier international", "Monde", "https://www.courrierinternational.com/feed/all/rss.xml"),
    ("lequipe", "L'Équipe", "Sport", "https://dwh.lequipe.fr/api/edito/rss?path=/"),
    ("numerama", "Numerama", "Tech", "https://www.numerama.com/feed/"),
    ("allocine", "Allociné", "Cinéma", "https://www.allocine.fr/rss/news.xml"),
    ("konbini", "Konbini", "Culture", "https://www.konbini.com/fr/feed/"),
]
NS = {"media": "http://search.yahoo.com/mrss/", "content": "http://purl.org/rss/1.0/modules/content/"}
_cache: dict = {"t": 0.0, "items": []}
http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0), follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (MediaHub personal reader)"})
TAG = re.compile(r"<[^>]+>")
IMG = re.compile(r'<img[^>]+src="([^"]+)"', re.I)


def _text(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", s or ""))).strip()


async def _fetch(key, name, section, url) -> list[dict]:
    try:
        r = await http.get(url)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:  # noqa: BLE001 - one broken feed must not break the page
        return []
    out = []
    for it in root.iter("item"):
        title = _text(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        raw = it.findtext("description") or ""
        full = it.findtext("content:encoded", namespaces=NS) or ""
        img = ""
        enc = it.find("enclosure")
        if enc is not None and (enc.get("type", "").startswith("image") or re.search(r"\.(jpe?g|png|webp)", enc.get("url", ""), re.I)):
            img = enc.get("url", "")
        for tag in ("media:content", "media:thumbnail"):
            el = it.find(tag, NS)
            if not img and el is not None and el.get("url"):
                img = el.get("url")
        if not img:
            m = IMG.search(raw) or IMG.search(full)
            img = m.group(1) if m else ""
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except Exception:  # noqa: BLE001
            ts = 0
        out.append({"source": key, "source_name": name, "section": section, "title": title, "link": link,
                    "summary": _text(raw)[:320], "image": img, "ts": ts})
    return out[:25]


@router.get("/api/news")
async def news():
    if time.time() - _cache["t"] > 600 or not _cache["items"]:
        lists = await asyncio.gather(*(_fetch(*s) for s in SOURCES))
        items = sorted((i for l in lists for i in l), key=lambda i: i["ts"], reverse=True)
        _cache.update(t=time.time(), items=items)
    return {"sources": [{"key": k, "name": n, "section": s} for k, n, s, _ in SOURCES], "items": _cache["items"]}
