"""Spotify charts without an account: top tracks, trending albums and artists.

The Web API needs a Premium app owner, so this reads Spotify's public pages instead:
- the embed page of a chart playlist gives its ordered track list (title, artists, track id);
- the public track page gives its cover, album (link + name) and artist links (OpenGraph tags);
- the public artist page gives the artist's photo (only for the top 30 artists).
Spotify throttles (429) after a couple hundred pages: then it stops, keeps what it has and continues 30 min later.
Everything is cached for 6 hours (memory + /data/spcharts.json), refreshed in the background.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter

from . import clients

router = APIRouter()

CHARTS = [  # (key, label, playlist id) — ids checked against open.spotify.com
    ("global", "World", "37i9dQZEVXbMDoHDwVN2tF"),        # Top 50 Global
    ("us", "USA", "37i9dQZEVXbLRQDuF5jeBp"),              # Top 50 USA
    ("fr", "France", "37i9dQZEVXbIPWwFssbupI"),           # Top 50 France
    ("rapus", "US rap", "37i9dQZF1DX0XUsuxWHRQd"),        # RapCaviar
    ("rapfr", "French rap", "37i9dQZF1DX1X23oiQRTB5"),    # PVNCHLNRS
    ("pop", "Pop", "37i9dQZF1DXcBWIGoYBM5M"),             # Today's Top Hits
    ("new", "New releases", "37i9dQZF1DX4JAvHpjipBk"),    # New Music Friday
]
PER_CHART = 30           # tracks looked up per chart (album + artist of each)
TTL = 6 * 3600
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"}   # a full browser UA gets the JS-only page without OpenGraph tags
CACHE_FILE = Path(os.environ.get("HUB_DATA_DIR", "/data")) / "spcharts.json"

_cache: dict = {}
_lock = asyncio.Lock()
_sem = asyncio.Semaphore(3)


def _load() -> None:
    global _cache
    if not _cache and CACHE_FILE.exists():
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a broken cache file is just rebuilt
            _cache = {}


class Throttled(Exception):
    """Spotify answered 429: stop for now, the next refresh continues where this one stopped."""


_blocked_until = 0.0


async def _get(url: str) -> str:
    global _blocked_until
    if time.time() < _blocked_until:
        raise Throttled()
    async with _sem:
        await asyncio.sleep(0.4)   # stay polite: ~7 pages / s at most
        r = await clients.client.get(url, headers=UA, timeout=15, follow_redirects=True)
        if r.status_code == 429:
            _blocked_until = time.time() + 1800
            raise Throttled()
        r.raise_for_status()
        return r.text


async def _playlist(pid: str) -> list[dict]:
    s = await _get(f"https://open.spotify.com/embed/playlist/{pid}")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', s, re.S)
    ent = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    out = []
    for t in ent.get("trackList", []):
        uri = t.get("uri", "")
        if uri.startswith("spotify:track:"):
            out.append({"id": uri.split(":")[-1], "title": t.get("title", ""), "artists": t.get("subtitle", ""),
                        "explicit": bool(t.get("isExplicit")), "ms": t.get("duration", 0)})
    return out


def _meta(s: str, key: str) -> list[str]:
    return [html.unescape(v) for v in re.findall(rf'<meta (?:property|name)="{re.escape(key)}" content="([^"]*)"', s)]


async def _page(kind: str, sid: str) -> dict:
    """OpenGraph info of a public track / artist page. A track's description is "Artists · Album · Song · Year"."""
    s = await _get(f"https://open.spotify.com/{kind}/{sid}")
    return {"title": (_meta(s, "og:title") or [""])[0], "image": (_meta(s, "og:image") or [""])[0],
            "desc": (_meta(s, "og:description") or [""])[0],
            "album": [u.rsplit("/", 1)[-1] for u in _meta(s, "music:album")][:1],
            "artists": [u.rsplit("/", 1)[-1] for u in _meta(s, "music:musician")]}


async def _safe(coro):
    try:
        return await coro
    except Exception:  # noqa: BLE001 - one missing page (or a 429) must not break the charts
        return None


async def _build() -> dict:
    lists = await asyncio.gather(*(_safe(_playlist(pid)) for _, _, pid in CHARTS))
    old_charts = {c["key"]: c for c in _cache.get("charts", [])}
    charts, track_ids = [], []
    for (key, label, pid), tracks in zip(CHARTS, lists):
        tracks = (tracks or [])[:PER_CHART] or old_charts.get(key, {}).get("tracks", [])   # throttled: keep the last list
        charts.append({"key": key, "label": label, "playlist": pid, "tracks": tracks})
        track_ids += [t["id"] for t in tracks if t["id"] not in track_ids]
    old = _cache.get("pages", {})   # lookups are kept between refreshes: a track's album never changes
    pages: dict[str, dict] = {}

    async def look(kind: str, sid: str):
        k = f"{kind}:{sid}"
        if k in old and old[k].get("title"):
            pages[k] = old[k]
        else:
            p = await _safe(_page(kind, sid))
            if p and p["title"]:
                pages[k] = p
    await asyncio.gather(*(look("track", t) for t in track_ids))

    # score = how high and how often an album / artist sits in the charts (rank 1 = 30 points, rank 30 = 1)
    albums: dict[str, dict] = {}
    artists: dict[str, dict] = {}
    for c in charts:
        for i, t in enumerate(c["tracks"]):
            tp = pages.get(f"track:{t['id']}", {})
            t["image"] = tp.get("image", t.get("image", ""))
            t["album"] = (tp.get("album") or [""])[0]
            pts = PER_CHART - i
            parts = tp.get("desc", "").split(" · ")
            if t["album"] and len(parts) >= 4:
                a = albums.setdefault(t["album"], {"id": t["album"], "name": parts[-3], "image": t["image"],
                                                   "info": f"{re.split(r',\s*', t['artists'])[0]} · {parts[-1]}", "score": 0})
                a["score"] += pts
            ids, names = tp.get("artists", []), re.split(r",\s*", t["artists"])
            for j, aid in enumerate(ids):
                name = names[j] if len(names) == len(ids) else (names[0] if j == 0 else "")
                if not name:
                    continue
                a = artists.setdefault(aid, {"id": aid, "name": name, "image": t["image"], "info": "", "score": 0})
                a["score"] += pts
    top_albums = sorted(albums.values(), key=lambda a: -a["score"])[:30]
    top_artists = sorted(artists.values(), key=lambda a: -a["score"])[:30]
    await asyncio.gather(*(look("artist", a["id"]) for a in top_artists))   # only their photo + listeners
    for a in top_artists:
        p = pages.get(f"artist:{a['id']}")
        if p:
            a["image"] = p["image"] or a["image"]
            a["info"] = p["desc"].replace("Artist · ", "")
    complete = all(f"track:{t}" in pages for t in track_ids) and all(f"artist:{a['id']}" in pages for a in top_artists)
    data = {"updated": time.time(), "complete": complete, "charts": charts,
            "albums": top_albums, "artists": top_artists, "pages": pages}
    if any(c["tracks"] for c in charts):
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


async def _refresh() -> None:
    global _cache
    if _lock.locked():
        return
    async with _lock:
        new = await _build()
        if any(c["tracks"] for c in new["charts"]):
            _cache = new


@router.get("/api/spotify/charts")
async def spotify_charts():
    _load()
    if not _cache:
        await _refresh()                         # first time: wait for it (~20 s)
    elif time.time() - _cache.get("updated", 0) > (TTL if _cache.get("complete") else 1800):
        asyncio.create_task(_refresh())          # stale: answer now, refresh in the background
    if not _cache:
        return {"updated": 0, "charts": [], "albums": [], "artists": []}
    return {k: v for k, v in _cache.items() if k != "pages"}
