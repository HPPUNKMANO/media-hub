"""Videos (a personal YouTube) and the AI news page.

Uses YouTube's public per-channel RSS feeds (no account, no API key) and plays videos with the
privacy-enhanced embed (youtube-nocookie.com) inside the hub.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import news

router = APIRouter()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
http = httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0), follow_redirects=True,
                         headers={"User-Agent": UA, "Cookie": "SOCS=CAI; CONSENT=YES+1", "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"})
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}

# Starting subscriptions (the user can add/remove their own from the Videos page)
DEFAULT_CHANNELS = [
    ("@TopGear", "Clarkson, Hammond & May"), ("@TheGrandTour", "Clarkson, Hammond & May"), ("@DriveTribe", "Clarkson, Hammond & May"),
    ("@TwoMinutePapers", "AI"), ("@aiexplained-official", "AI"), ("@mreflow", "AI"), ("@Fireship", "AI"),
    ("@DefendIntelligence", "AI"), ("@Micode", "AI"), ("@Underscore_", "AI"),
    ("@AliAbdaal", "Self-improvement"), ("@hubermanlab", "Self-improvement"), ("@MattDAvella", "Self-improvement"),
    ("@TheDiaryOfACEO", "Self-improvement"), ("@ImprovementPill", "Self-improvement"), ("@OlivierRoland", "Self-improvement"),
    ("@ErmiteModerne", "Self-improvement"),
    ("@PremierPadelOfficial", "Padel"), ("@PadelFIP", "Padel"), ("@ThePadelSchool", "Padel"), ("@PadelMagazine", "Padel"),
]
AI_CHANNELS = ["@TwoMinutePapers", "@aiexplained-official", "@mreflow", "@Fireship", "@DefendIntelligence", "@Underscore_"]
AI_SOURCES = [
    ("verge-ai", "The Verge", "AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("techcrunch-ai", "TechCrunch", "AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("mit-ai", "MIT Tech Review", "AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ("ars-ai", "Ars Technica", "AI", "https://arstechnica.com/ai/feed/"),
    ("openai", "OpenAI", "Lab", "https://openai.com/news/rss.xml"),
    ("deepmind", "Google DeepMind", "Lab", "https://deepmind.google/blog/rss.xml"),
    ("hf", "Hugging Face", "Open source", "https://huggingface.co/blog/feed.xml"),
    ("actuia", "ActuIA", "IA (FR)", "https://www.actuia.com/feed/"),
    ("numerama", "Numerama", "Tech (FR)", "https://www.numerama.com/feed/"),
]
_cache: dict = {}


def _db():
    from .main import kv_get, kv_set  # late import: main imports this module
    return kv_get, kv_set


async def resolve(ref: str) -> dict | None:
    """'@handle', a channel URL or a UC… id -> {id, title}."""
    ref = ref.strip()
    m = re.search(r"(UC[\w-]{22})", ref)
    if m:
        url = f"https://www.youtube.com/channel/{m.group(1)}"
    else:
        h = re.search(r"@([\w.\-]+)", ref)
        if not h:
            return None
        url = f"https://www.youtube.com/@{h.group(1)}"
    try:
        r = await http.get(url)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    cid = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', r.text) \
        or re.search(r'"externalId":"(UC[\w-]{22})"', r.text)
    title = re.search(r'<meta property="og:title" content="([^"]+)"', r.text)
    avatar = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
    if not cid:
        return None
    import html as _h
    return {"id": cid.group(1), "title": _h.unescape(title.group(1) if title else cid.group(1)),
            "avatar": avatar.group(1) if avatar else ""}


async def channel_videos(cid: str) -> list[dict]:
    hit = _cache.get(cid)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        r = await http.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": cid})
        root = ET.fromstring(r.content)
    except Exception:  # noqa: BLE001
        return hit[1] if hit else []
    out = []
    author = root.findtext("a:title", default="", namespaces=NS)
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        if not vid:
            continue
        g = e.find("media:group", NS)
        thumb = g.find("media:thumbnail", NS).get("url") if g is not None and g.find("media:thumbnail", NS) is not None else ""
        stats = g.find("media:community/media:statistics", NS) if g is not None else None
        link = e.find("a:link", NS).get("href", "") if e.find("a:link", NS) is not None else ""
        out.append({"id": vid, "title": e.findtext("a:title", default="", namespaces=NS), "channel": author, "channel_id": cid,
                    "published": e.findtext("a:published", default="", namespaces=NS),
                    "views": int(stats.get("views", 0)) if stats is not None else 0,
                    "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if not thumb else thumb.replace("hqdefault", "hqdefault"),
                    "short": "/shorts/" in link})
    _cache[cid] = (time.time(), out)
    return out


async def _channels(key: str, defaults: list) -> list[dict]:
    kv_get, kv_set = _db()
    raw = kv_get(key)
    if raw:
        return json.loads(raw)
    pairs = [d if isinstance(d, tuple) else (d, "AI") for d in defaults]
    found = await asyncio.gather(*(resolve(h) for h, _ in pairs))
    resolved = [{**c, "cat": cat} for c, (_, cat) in zip(found, pairs) if c]
    kv_set(key, json.dumps(resolved))
    return resolved


@router.get("/api/yt/channels")
async def yt_channels():
    return {"channels": await _channels("yt_channels_v2", DEFAULT_CHANNELS)}


@router.post("/api/yt/channels")
async def yt_add(request: Request):
    body = await request.json()
    ref = str(body.get("ref", ""))
    ch = await resolve(ref)
    if not ch:
        raise HTTPException(404, "Channel not found — paste its link (youtube.com/@name) or its @name.")
    chans = await _channels("yt_channels_v2", DEFAULT_CHANNELS)
    if not any(c["id"] == ch["id"] for c in chans):
        ch["cat"] = str(body.get("cat") or "My channels")[:40]
        chans.insert(0, ch)
        _db()[1]("yt_channels_v2", json.dumps(chans))
    return ch


@router.delete("/api/yt/channels/{cid}")
async def yt_remove(cid: str):
    chans = [c for c in await _channels("yt_channels_v2", DEFAULT_CHANNELS) if c["id"] != cid]
    _db()[1]("yt_channels_v2", json.dumps(chans))
    return {"ok": True}


@router.get("/api/yt/feed")
async def yt_feed(ch: str = "", cat: str = ""):
    chans = await _channels("yt_channels_v2", DEFAULT_CHANNELS)
    ids = [ch] if ch else [c["id"] for c in chans if not cat or c.get("cat") == cat]
    lists = await asyncio.gather(*(channel_videos(i) for i in ids))
    vids = sorted((v for l in lists for v in l if not v["short"]), key=lambda v: v["published"], reverse=True)
    return {"videos": vids[:120]}


@router.get("/api/ai")
async def ai_news():
    chans = await _channels("ai_channels", AI_CHANNELS)
    arts, vids = await asyncio.gather(
        asyncio.gather(*(news._fetch(*s) for s in AI_SOURCES)),
        asyncio.gather(*(channel_videos(c["id"]) for c in chans)))
    articles = sorted((i for l in arts for i in l), key=lambda i: i["ts"], reverse=True)
    if any(s[0] == "numerama" for s in AI_SOURCES):   # Numerama is general tech: keep only AI stories
        kw = re.compile(r"\b(IA|AI|intelligence artificielle|ChatGPT|OpenAI|Claude|Anthropic|Gemini|Mistral|LLM|robot)\b", re.I)
        articles = [a for a in articles if a["source"] != "numerama" or kw.search(a["title"] + " " + a["summary"])]
    news.remember(articles)
    videos = sorted((v for l in vids for v in l if not v["short"]), key=lambda v: v["published"], reverse=True)
    recap = {}
    try:
        from .main import DATA_DIR
        f = DATA_DIR / "ai_recap.json"
        recap = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        recap = {}
    return {"recap": recap, "articles": articles[:80], "videos": videos[:24], "channels": chans,
            "sources": [{"key": k, "name": n} for k, n, _, _ in AI_SOURCES]}
