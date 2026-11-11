"""Live TV inside the hub: reads the curated, tested M3U and relays the HLS streams.

Relaying (instead of letting the browser fetch streams directly) fixes the two things that
break most free channels in a browser: CORS and the User-Agent some broadcasters require.
Only URLs that this server itself signed are relayed, so this is not an open proxy.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter()
M3U = Path(os.environ.get("HUB_DATA_DIR", "/data")) / "iptv" / "france.m3u"
SECRET = secrets.token_bytes(32)
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
GROUP_ORDER = ["Cinéma", "Séries", "Enfants & Anime", "Info", "Docs & Découverte", "Sport", "Musique"]
http = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True)

_cache: dict = {"mtime": 0.0, "channels": []}


def channels() -> list[dict]:
    if not M3U.exists():
        return []
    mtime = M3U.stat().st_mtime
    if mtime != _cache["mtime"]:
        out, inf, ua = [], None, ""
        for line in M3U.read_text(encoding="utf-8").splitlines():
            if line.startswith("#EXTINF"):
                inf, ua = line, ""
                m = re.search(r'http-user-agent="([^"]+)"', line)
                ua = m.group(1) if m else ""
            elif line.startswith("#EXTVLCOPT:http-user-agent="):
                ua = line.split("=", 1)[1]
            elif line.startswith("http") and inf:
                name = inf.rsplit('",', 1)[-1] if '",' in inf else inf.split(",", 1)[-1]
                name = re.sub(r"\s*\((\d+p|\d+i)\)", "", name).replace("[Not 24/7]", "").strip()
                g = re.search(r'group-title="([^"]*)"', inf)
                logo = re.search(r'tvg-logo="([^"]*)"', inf)
                ref = re.search(r'http-referrer="([^"]*)"', inf)
                out.append({"id": len(out), "name": name, "group": g.group(1) if g else "Autres",
                            "logo": logo.group(1) if logo else "", "url": line.strip(), "ua": ua,
                            "referrer": ref.group(1) if ref else ""})
                inf = None
        _cache.update(mtime=mtime, channels=out)
    return _cache["channels"]


def _sign(url: str, cid: int) -> str:
    return hmac.new(SECRET, f"{cid}|{url}".encode(), hashlib.sha256).hexdigest()[:24]


def _relay_url(url: str, cid: int) -> str:
    u = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return f"/api/tv/relay/{cid}/{_sign(url, cid)}/{u}"


def _rewrite(playlist: str, base: str, cid: int) -> str:
    def fix_attr(m: re.Match) -> str:
        return f'URI="{_relay_url(urljoin(base, m.group(1)), cid)}"'
    lines = []
    for line in playlist.splitlines():
        s = line.strip()
        if not s:
            lines.append(line)
        elif s.startswith("#"):
            lines.append(re.sub(r'URI="([^"]+)"', fix_attr, line))
        else:
            lines.append(_relay_url(urljoin(base, s), cid))
    return "\n".join(lines) + "\n"


@router.get("/api/tv/channels")
async def list_channels():
    chs = channels()
    groups = sorted({c["group"] for c in chs}, key=lambda g: (GROUP_ORDER.index(g) if g in GROUP_ORDER else 99, g))
    return {"groups": groups, "channels": [{k: c[k] for k in ("id", "name", "group", "logo")} for c in chs]}


@router.get("/api/tv/play/{cid}")
async def play(cid: int):
    chs = channels()
    if not 0 <= cid < len(chs):
        raise HTTPException(404, "unknown channel")
    return {"src": _relay_url(chs[cid]["url"], cid), "name": chs[cid]["name"]}


@router.get("/api/tv/relay/{cid}/{sig}/{enc}")
async def relay(cid: int, sig: str, enc: str):
    try:
        url = base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4)).decode()
    except Exception:
        raise HTTPException(400)
    chs = channels()
    if not 0 <= cid < len(chs) or not hmac.compare_digest(sig, _sign(url, cid)) or not url.startswith(("http://", "https://")):
        raise HTTPException(403)
    ch = chs[cid]
    headers = {"User-Agent": ch["ua"] or DEFAULT_UA}
    if ch["referrer"]:
        headers["Referer"] = ch["referrer"]
    try:
        r = await http.get(url, headers=headers)
    except httpx.HTTPError:
        raise HTTPException(502, "channel unreachable")
    if r.status_code >= 400:
        raise HTTPException(r.status_code if r.status_code in (403, 404, 410) else 502)
    body = r.content
    if body[:7] == b"#EXTM3U":
        text = _rewrite(body.decode("utf-8", "replace"), str(r.url), cid)
        return Response(text, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-store"})
    return Response(body, media_type=r.headers.get("content-type", "video/mp2t"), headers={"Cache-Control": "max-age=30"})
