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
JUNK = re.compile(r"(cookies?|abonnez-vous|abonnement|newsletter|lire aussi|à lire aussi|lire dans l.app|ouvre un nouvel onglet|nouvel onglet|sauvegarder|copier le lien|lien copié|partager|facebook|messenger|whatsapp|linkedin|twitter|\bX\b$|se connecter|créer un compte|s.inscrire|publicité|google news|google discover|réagir|commentaires?|subscribe|sign up|log in|tous droits|©)", re.I)
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
        if tag.lower() == "li" and len(t) < 70:   # menus, share buttons, tag lists
            continue
        if JUNK.search(t) and len(t) < 260:
            continue
        blocks.append({"t": tag.lower(), "x": t})
    title = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    image = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    paywall = len(" ".join(b["x"] for b in blocks)) < 600
    _highlight(blocks[:120], html.unescape(title.group(1)) if title else "")
    return {"title": html.unescape(title.group(1)) if title else "", "image": image.group(1) if image else "",
            "blocks": blocks[:120], "url": url, "short": paywall}


SENT = re.compile(r"(?<=[.!?…])[»\"”]?\s+(?=[«\"“A-ZÀ-Ý0-9])")


def _highlight(blocks: list[dict], title: str) -> None:
    """Marks the sentences that answer the headline, so the reader can show them in bold.
    The lead sentence (journalists put the answer first) + the sentences sharing the most words with the title,
    with a bonus for figures and quotes. 3 to 5 sentences, about 1 in 4. Adds "s": [[sentence, bold], ...] to text blocks."""
    tw = _words(title)
    cands = []   # (score, block index, sentence index)
    for bi, b in enumerate(blocks):
        if b["t"] not in ("p", "li"):
            continue
        b["s"] = [[s, False] for s in SENT.split(b["x"]) if s.strip()]
        for si, (s, _) in enumerate(b["s"]):
            if len(s) < 50:
                continue
            w = _words(s)
            score = 2.0 * len(w & tw) + (1.0 if re.search(r"\d", s) else 0) + (0.8 if re.search(r"[«“\"]", s) else 0)
            score += max(0.0, 2.5 - 0.25 * len(cands))   # earlier sentences matter more
            cands.append((score, bi, si))
    if not cands:
        return
    pick = {(cands[0][1], cands[0][2])}   # the lead sentence
    n = max(3, min(5, len(cands) // 4))
    for score, bi, si in sorted(cands[1:], key=lambda c: -c[0]):
        if len(pick) >= n or score < 3:
            break
        pick.add((bi, si))
    for bi, si in pick:
        blocks[bi]["s"][si][1] = True


STOP = set("""le la les un une des du de d l au aux et ou en à a dans sur pour par avec sans sous ce cette ces son sa ses leur leurs
qui que quoi dont est sont été être fait faire plus moins pas ne n se s il elle ils elles on nous vous je tu y après avant comme
entre contre vers chez selon depuis lors face nouveau nouvelle nouveaux deux trois va vont peut doit the of to in and for on with
video vidéo direct live photos info infos ce qu quand comment pourquoi tout tous toute toutes alors encore aussi déjà très bien""".split())


def _words(t: str) -> set[str]:
    import unicodedata
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]{4,}", t) if w not in STOP}


def essentials(items: list[dict], n: int = 8) -> list[dict]:
    """'L'essentiel': groups headlines that several newspapers cover (the more papers, the bigger the story)."""
    recent = [i for i in items if i["ts"] and time.time() - i["ts"] < 36 * 3600][:250]
    groups: list[dict] = []
    for it in recent:
        w = _words(it["title"])
        for g in groups:
            if len(w & g["words"]) >= 2:   # compare with the story's first headline only (no drift between topics)
                g["items"].append(it); break
        else:
            groups.append({"words": set(w), "items": [it]})
    out = []
    for g in groups:
        srcs = {i["source_name"] for i in g["items"]}
        if len(srcs) < 2:
            continue
        best = g["items"][0] if len(g["items"][0]["summary"]) > 60 else max(
            (i for i in g["items"] if len(_words(i["title"]) & g["words"]) >= 2), key=lambda i: (len(i["summary"]), bool(i["image"])))
        out.append({"title": best["title"], "summary": best["summary"][:260], "link": best["link"], "image": best["image"],
                    "sources": sorted(srcs), "count": len(srcs), "ts": max(i["ts"] for i in g["items"]),
                    "section": best["section"], "source_name": best["source_name"]})
    out.sort(key=lambda s: (s["count"], s["ts"]), reverse=True)
    return out[:n]


@router.get("/api/news")
async def news():
    if time.time() - _cache["t"] > 300 or not _cache["items"]:
        lists = await asyncio.gather(*(_fetch(*s) for s in SOURCES))
        items = sorted((i for l in lists for i in l), key=lambda i: i["ts"], reverse=True)
        _cache.update(t=time.time(), items=items)
        remember(items)
    return {"sources": [{"key": k, "name": n, "section": s} for k, n, s, _ in SOURCES], "items": _cache["items"],
            "essentials": essentials(_cache["items"])}
