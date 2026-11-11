"""Now playing: reads the song title that radio streams embed in their audio (ICY metadata, "StreamTitle").
Only stations listed in the hub's catalog can be queried. Results are cached 15 s per station."""
from __future__ import annotations

import re
import time

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()
_cache: dict[str, tuple[float, dict]] = {}
UAS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36", "VLC/3.0.20 LibVLC/3.0.20"]


def _allowed() -> set[str]:
    from .main import CATALOG
    return {r["url"] for r in CATALOG.get("radios", [])}


def _clean(title: str) -> dict:
    t = re.sub(r"\s*[§#]\d+\s*$", "", title)            # some stations append internal track ids
    t = re.sub(r"\s+", " ", t).strip(" -|")
    if not t or len(t) < 3 or re.fullmatch(r"[\d\s-]+", t) or re.search(r"now playing info|unknown|^live$|^-$", t, re.I) or re.search(r"^(pub|publicit|jingle|nrj|skyrock|fun radio|rtl2?|europe ?\d|rfm|nostalgie|chérie)\b", t, re.I) and " - " not in t:
        return {}
    artist, sep, song = t.partition(" - ")
    return {"artist": artist.strip(), "title": song.strip()} if sep else {"artist": "", "title": t}


async def icy_title(url: str, ua: str) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=True) as c:
        async with c.stream("GET", url, headers={"Icy-MetaData": "1", "User-Agent": ua}) as r:
            metaint = int(r.headers.get("icy-metaint", "0") or 0)
            if not metaint:
                return {}
            buf = b""
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > metaint + 1:
                    length = buf[metaint] * 16
                    if len(buf) >= metaint + 1 + length:
                        meta = buf[metaint + 1: metaint + 1 + length].decode("utf-8", "replace")
                        m = re.search(r"StreamTitle='(.*?)';", meta)
                        return _clean(m.group(1)) if m else {}
                if len(buf) > metaint + 5000:
                    break
    return {}


@router.get("/api/radio/now")
async def now_playing(url: str):
    if url not in _allowed():
        raise HTTPException(403)
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < 15:
        return hit[1]
    try:
        info = {}
        for ua in UAS:   # some stations answer browsers, others only media players
            info = await icy_title(url, ua)
            if info:
                break
    except (httpx.HTTPError, ValueError, IndexError):
        info = {}
    _cache[url] = (time.time(), info)
    return info
