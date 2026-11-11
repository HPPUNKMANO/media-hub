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


KNOWN_HOSTS: set[str] = set()   # filled from the feeds: the reader only opens articles we listed (no open proxy)
P_TAG = re.compile(r"<(p|h2|h3|li|blockquote)\b[^>]*>(.*?)</\1>", re.I | re.S)


def remember(items: list[dict]) -> None:
    from urllib.parse import urlparse
    for i in items:
        KNOWN_HOSTS.add(urlparse(i["link"]).hostname or "")


@router.get("/api/read")
async def read(url: str):
    """In-app reader: fetches an article from a known feed and returns its clean text."""
    from urllib.parse import urlparse
    from fastapi import HTTPException
    host = urlparse(url).hostname or ""
    if not url.startswith(("http://", "https://")) or host not in KNOWN_HOSTS:
        raise HTTPException(403, "Only articles listed in the hub can be opened here.")
    try:
        r = await http.get(url)
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(502, "The newspaper's site did not answer.")
    page = r.text
    body = re.search(r"<article\b.*?</article>", page, re.S | re.I)
    scope = body.group(0) if body and len(body.group(0)) > 2000 else page
    scope = re.sub(r"<(script|style|nav|aside|footer|form|figure)\b.*?</\1>", " ", scope, flags=re.S | re.I)
    blocks = []
    for tag, inner in P_TAG.findall(scope):
        t = _text(inner)
        if len(t) < 40 and tag.lower() == "p":
            continue
        if re.search(r"(cookies?|abonnez-vous|newsletter|Lire aussi|À lire aussi|subscribe|sign up|Tous droits)", t, re.I) and len(t) < 200:
            continue
        blocks.append({"t": tag.lower(), "x": t})
    title = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    image = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    paywall = len(" ".join(b["x"] for b in blocks)) < 600
    return {"title": html.unescape(title.group(1)) if title else "", "image": image.group(1) if image else "",
            "blocks": blocks[:120], "url": url, "short": paywall}


@router.get("/api/news")
async def news():
    if time.time() - _cache["t"] > 300 or not _cache["items"]:
        lists = await asyncio.gather(*(_fetch(*s) for s in SOURCES))
        items = sorted((i for l in lists for i in l), key=lambda i: i["ts"], reverse=True)
        _cache.update(t=time.time(), items=items)
        remember(items)
    return {"sources": [{"key": k, "name": n, "section": s} for k, n, s, _ in SOURCES], "items": _cache["items"]}
