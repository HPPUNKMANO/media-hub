"""Padel: detects live streams on the padel YouTube channels the user follows (category "Padel"),
so live matches show up in the hub and play inside it. Cached 5 minutes."""
from __future__ import annotations

import asyncio
import re
import time

from fastapi import APIRouter

from . import youtube

router = APIRouter()
_cache: dict = {"t": 0.0, "data": None}
VID = re.compile(r'"videoId":"([\w-]{11})"')


async def _live_info(vid: str) -> dict | None:
    try:
        r = await youtube.http.get(f"https://www.youtube.com/watch?v={vid}")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r'"liveBroadcastDetails":\{([^}]*)\}', r.text)
    if not m:
        return None
    d = m.group(1)
    title = re.search(r'<meta name="title" content="([^"]+)"', r.text)
    import html
    return {"id": vid, "title": html.unescape(title.group(1)) if title else vid,
            "live": '"isLiveNow":true' in d,
            "start": (re.search(r'"startTimestamp":"([^"]+)"', d) or [None, ""])[1],
            "ended": '"endTimestamp"' in d}


async def _channel_lives(ch: dict) -> list[dict]:
    """Every stream that is live now (big tournaments run several courts at once) + upcoming ones."""
    try:
        r = await youtube.http.get(f"https://www.youtube.com/channel/{ch['id']}/streams")
    except Exception:  # noqa: BLE001
        return []
    ids = list(dict.fromkeys(VID.findall(r.text)))[:8]
    infos = await asyncio.gather(*(_live_info(v) for v in ids))
    out = []
    for i in infos:
        if i and (i["live"] or (not i["ended"] and i["start"])):
            out.append({**i, "channel": ch["title"], "channel_id": ch["id"], "avatar": ch.get("avatar", ""),
                        "thumb": f"https://i.ytimg.com/vi/{i['id']}/hqdefault.jpg", "upcoming": not i["live"]})
    return out


@router.get("/api/padel")
async def padel():
    if _cache["data"] is None or time.time() - _cache["t"] > 300:
        chans = [c for c in await youtube._channels("yt_channels_v2", youtube.DEFAULT_CHANNELS) if c.get("cat") == "Padel"]
        lists = await asyncio.gather(*(_channel_lives(c) for c in chans))
        items = [i for l in lists for i in l]
        live = [i for i in items if i["live"]]
        upcoming = sorted([i for i in items if i["upcoming"]], key=lambda i: i["start"])
        _cache.update(t=time.time(), data={"live": live, "upcoming": upcoming[:12], "channels": chans})
    return _cache["data"]
