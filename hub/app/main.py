"""Media Hub: one home page for the local servers + the legal free-streaming catalog."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import clients

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("HUB_DATA_DIR", "/data"))
CATALOG = json.loads((HERE / "data" / "catalog.json").read_text(encoding="utf-8"))
PORTS = {
    "jellyfin": int(os.environ.get("JELLYFIN_PORT", "8096")),
    "navidrome": int(os.environ.get("NAVIDROME_PORT", "4533")),
    "audiobookshelf": int(os.environ.get("ABS_PORT", "13378")),
}

app = FastAPI(title="Media Hub", docs_url=None, redoc_url=None)

from . import news, padel, radio, tv, youtube  # noqa: E402  (live TV relay, headlines, videos + AI news, padel lives)
app.include_router(padel.router)
app.include_router(radio.router)
app.include_router(tv.router)
app.include_router(news.router)
app.include_router(youtube.router)


# ----------------------------------------------------------------- favorites db
def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / "hub.db")
    con.execute("CREATE TABLE IF NOT EXISTS favorites (id TEXT PRIMARY KEY, added REAL)")
    return con


# ----------------------------------------------------------------- helpers
async def safe(coro, default=None):
    """Run a service call; a service that is down or not configured yields an empty section."""
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 - a broken service must not break the page
        return default if default is not None else {"error": f"{exc.__class__.__name__}"}


# ----------------------------------------------------------------- API
@app.get("/api/config")
async def config():
    return {"ports": PORTS, "lan_url": os.environ.get("HUB_LAN_URL", "")}


@app.get("/api/status")
async def status():
    return await clients.status()


@app.get("/api/home")
async def home():
    resume, latest, recent_albums, new_albums, podcasts = await asyncio.gather(
        safe(clients.jf_resume(), []), safe(clients.jf_latest(), []),
        safe(clients.nd_albums("recent"), []), safe(clients.nd_albums("newest"), []),
        safe(clients.abs_recent(), []),
    )
    return {"resume": resume, "latest": latest, "recent_albums": recent_albums,
            "new_albums": new_albums, "podcasts": podcasts}


@app.get("/api/watch")
async def watch():
    libs, latest, movies, series, resume = await asyncio.gather(
        safe(clients.jf_libraries(), []), safe(clients.jf_latest(30), []),
        safe(clients.jf_items("Movie"), []), safe(clients.jf_items("Series"), []), safe(clients.jf_resume(), []))
    return {"libraries": libs, "latest": latest, "movies": movies, "series": series, "resume": resume}


@app.get("/api/listen")
async def listen():
    recent, frequent, random_, radios = await asyncio.gather(
        safe(clients.nd_albums("recent"), []), safe(clients.nd_albums("frequent"), []),
        safe(clients.nd_albums("random", 12), []), safe(clients.nd_radios(), []))
    return {"recent": recent, "frequent": frequent, "random": random_, "radios": radios}


@app.get("/api/search")
async def search(q: str):
    q = q.strip()
    if len(q) < 2:
        return {"jellyfin": [], "navidrome": [], "catalog": []}
    jf, nd = await asyncio.gather(safe(clients.jf_search(q), []), safe(clients.nd_search(q), []))
    ql = q.lower()
    cat = [e for e in CATALOG["entries"]
           if ql in " ".join([e["name"], e.get("description", ""), " ".join(e.get("topics", [])),
                              e.get("category", "")]).lower()]
    return {"jellyfin": jf, "navidrome": nd, "catalog": cat[:30]}


_SPOTIFY_ART: dict[str, str] = {}


@app.get("/api/spotify")
async def spotify():
    """Curated Spotify playlists with their cover art (public oEmbed, no account or key needed)."""
    async def art(pid: str) -> str:
        if pid not in _SPOTIFY_ART:
            try:
                r = await clients.client.get("https://open.spotify.com/oembed",
                                             params={"url": f"https://open.spotify.com/playlist/{pid}"}, timeout=8)
                _SPOTIFY_ART[pid] = r.json().get("thumbnail_url", "")
            except Exception:  # noqa: BLE001 - no cover is fine, retry next time
                return ""
        return _SPOTIFY_ART[pid]
    lists = CATALOG.get("spotify_playlists", [])
    images = await asyncio.gather(*(art(p["id"]) for p in lists))
    return {"playlists": [{**p, "image": img} for p, img in zip(lists, images)]}


# ---- Spotify account (Authorization Code + PKCE, no client secret needed).
# The user creates a free "app" on developer.spotify.com and pastes its Client ID in the hub.
SPOTIFY_REDIRECT = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/api/spotify/callback")
SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative user-library-read user-read-private"


def kv_get(key: str) -> str:
    con = db()
    con.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    row = con.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    con.close()
    return row[0] if row else ""


def kv_set(key: str, value: str) -> None:
    con = db()
    con.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?, ?)", (key, value))
    con.commit()
    con.close()


@app.get("/api/spotify/account")
async def spotify_account():
    return {"client_id": bool(kv_get("sp_client_id")), "connected": bool(kv_get("sp_refresh")),
            "name": kv_get("sp_name"), "redirect_uri": SPOTIFY_REDIRECT}


@app.post("/api/spotify/client")
async def spotify_client(request: Request):
    cid = str((await request.json()).get("client_id", "")).strip()
    if cid and not (len(cid) == 32 and cid.isalnum()):
        raise HTTPException(400, "A Spotify Client ID is 32 letters and digits.")
    kv_set("sp_client_id", cid)
    return {"ok": True}


@app.get("/api/spotify/login")
async def spotify_login():
    import base64, hashlib, secrets
    from urllib.parse import urlencode
    from fastapi.responses import RedirectResponse
    cid = kv_get("sp_client_id")
    if not cid:
        raise HTTPException(400, "Add your Spotify Client ID first.")
    verifier = secrets.token_urlsafe(64)[:96]
    state = secrets.token_urlsafe(16)
    kv_set("sp_verifier", verifier)
    kv_set("sp_state", state)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = urlencode({"client_id": cid, "response_type": "code", "redirect_uri": SPOTIFY_REDIRECT, "scope": SPOTIFY_SCOPES,
                   "code_challenge_method": "S256", "code_challenge": challenge, "state": state})
    return RedirectResponse(f"https://accounts.spotify.com/authorize?{q}")


async def _sp_token(data: dict) -> dict:
    r = await clients.client.post("https://accounts.spotify.com/api/token", data={**data, "client_id": kv_get("sp_client_id")})
    r.raise_for_status()
    tok = r.json()
    kv_set("sp_access", tok["access_token"])
    kv_set("sp_expires", str(time.time() + tok.get("expires_in", 3600) - 60))
    if tok.get("refresh_token"):
        kv_set("sp_refresh", tok["refresh_token"])
    return tok


@app.get("/api/spotify/callback")
async def spotify_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import HTMLResponse
    back = os.environ.get("HUB_PUBLIC_URL", "http://localhost:8080")
    if error or not code or state != kv_get("sp_state"):
        return HTMLResponse(f"<p>Spotify connection cancelled ({error or 'invalid state'}). <a href='{back}/#spotify'>Back</a></p>", 400)
    await _sp_token({"grant_type": "authorization_code", "code": code, "redirect_uri": SPOTIFY_REDIRECT,
                     "code_verifier": kv_get("sp_verifier")})
    me = await _sp_api("/me")
    kv_set("sp_name", (me or {}).get("display_name") or (me or {}).get("id", ""))
    return HTMLResponse(f"<meta http-equiv='refresh' content='0;url={back}/#spotify'><p>Connected. <a href='{back}/#spotify'>Back to Media Hub</a></p>")


async def _sp_api(path: str, **params):
    if not kv_get("sp_refresh"):
        return None
    if time.time() > float(kv_get("sp_expires") or 0):
        await _sp_token({"grant_type": "refresh_token", "refresh_token": kv_get("sp_refresh")})
    r = await clients.client.get(f"https://api.spotify.com/v1{path}", params=params,
                                 headers={"Authorization": f"Bearer {kv_get('sp_access')}"})
    if r.status_code == 401:
        await _sp_token({"grant_type": "refresh_token", "refresh_token": kv_get("sp_refresh")})
        r = await clients.client.get(f"https://api.spotify.com/v1{path}", params=params,
                                     headers={"Authorization": f"Bearer {kv_get('sp_access')}"})
    r.raise_for_status()
    return r.json()


@app.get("/api/spotify/mine")
async def spotify_mine():
    try:
        data = await _sp_api("/me/playlists", limit=50)
    except httpx.HTTPError as exc:
        return JSONResponse({"error": f"Spotify: {exc.__class__.__name__}"}, status_code=502)
    if data is None:
        return {"connected": False, "playlists": []}
    out = [{"id": p["id"], "name": p["name"], "mood": f"{p.get('tracks', {}).get('total', '')} tracks".strip(),
            "image": (p.get("images") or [{}])[0].get("url", "")} for p in data.get("items", []) if p]
    return {"connected": True, "name": kv_get("sp_name"), "playlists": out}


@app.post("/api/spotify/logout")
async def spotify_logout():
    for k in ("sp_refresh", "sp_access", "sp_expires", "sp_name"):
        kv_set(k, "")
    return {"ok": True}


@app.get("/api/weekly")
async def weekly():
    """Summary written every Sunday by the weekly Claude curator (scripts/weekly)."""
    f = DATA_DIR / "weekly.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        return {}


@app.get("/api/catalog")
async def catalog():
    con = db()
    favs = {r[0] for r in con.execute("SELECT id FROM favorites")}
    con.close()
    return {**CATALOG, "favorites": sorted(favs)}


@app.put("/api/favorites/{entry_id}")
async def add_favorite(entry_id: str):
    if entry_id not in {e["id"] for e in CATALOG["entries"]}:
        raise HTTPException(404, "unknown catalog entry")
    con = db()
    con.execute("INSERT OR IGNORE INTO favorites(id, added) VALUES(?, ?)", (entry_id, time.time()))
    con.commit()
    con.close()
    return {"ok": True}


@app.delete("/api/favorites/{entry_id}")
async def remove_favorite(entry_id: str):
    con = db()
    con.execute("DELETE FROM favorites WHERE id=?", (entry_id,))
    con.commit()
    con.close()
    return {"ok": True}


# ---- organizer proxy
@app.get("/api/organizer/{path:path}")
async def organizer_get(path: str):
    if path not in {"report", "reports", "queues", "health"} and not path.startswith("reports/"):
        raise HTTPException(404)
    try:
        r = await clients.client.get(f"{clients.ORG_URL}/{path}")
        return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.HTTPError:
        return JSONResponse({"error": "organizer is not reachable"}, status_code=503)


@app.post("/api/organizer/run")
async def organizer_run(request: Request):
    body = await request.json() if await request.body() else {}
    try:
        r = await clients.client.post(f"{clients.ORG_URL}/run", json={"dry_run": bool(body.get("dry_run", True))},
                                      timeout=httpx.Timeout(1800.0, connect=3.0))
        return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.HTTPError:
        return JSONResponse({"error": "organizer is not reachable"}, status_code=503)


# ---- image proxy (keeps API keys server-side, adds browser caching)
@app.get("/api/img/{service}/{item_id}")
async def image(service: str, item_id: str):
    fetch = {"jf": clients.jf_image, "jfb": clients.jf_backdrop, "nd": clients.nd_image,
             "abs": clients.abs_image}.get(service)
    if not fetch or not item_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(404)
    try:
        r = await fetch(item_id)
    except httpx.HTTPError:
        raise HTTPException(404)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(404)
    return Response(r.content, media_type=r.headers["content-type"], headers={"Cache-Control": "public, max-age=86400"})


# ----------------------------------------------------------------- frontend
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/sw.js")
async def service_worker():
    # served from the root so it controls the whole hub (needed to install it as an app)
    return FileResponse(HERE / "static" / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(HERE / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})
