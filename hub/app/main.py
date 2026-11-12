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
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles

from . import clients

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("HUB_DATA_DIR", "/data"))
CATALOG = json.loads((HERE / "data" / "catalog.json").read_text(encoding="utf-8"))
NO_FILMS = ("public-domain", "films")   # the free films are gone from Discover (user: not worth it)
CATALOG["entries"] = [e for e in CATALOG["entries"] if e.get("category") not in NO_FILMS]
if isinstance(CATALOG.get("categories"), dict):
    CATALOG["categories"] = {k: v for k, v in CATALOG["categories"].items() if k not in NO_FILMS}
elif isinstance(CATALOG.get("categories"), list):
    CATALOG["categories"] = [c for c in CATALOG["categories"] if (c.get("id") if isinstance(c, dict) else c) not in NO_FILMS]
PORTS = {
    "jellyfin": int(os.environ.get("JELLYFIN_PORT", "8096")),
    "navidrome": int(os.environ.get("NAVIDROME_PORT", "4533")),
    "audiobookshelf": int(os.environ.get("ABS_PORT", "13378")),
}

app = FastAPI(title="Media Hub", docs_url=None, redoc_url=None)

from . import news, notes, radio, sport, tv, youtube  # noqa: E402  (live TV relay, headlines, AI news, sport scores + lives)
from . import auth  # noqa: E402
app.middleware("http")(auth.middleware)   # every /api route needs a logged-in account
app.include_router(auth.router)
app.include_router(notes.router)   # tasks with reminders (push notifications) + daily notes
app.add_event_handler("startup", notes.start)
app.include_router(sport.router)
app.add_event_handler("startup", sport.start)   # scores + lives kept fresh in the background
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
async def home(request: Request):
    hidden = request.state.user["hidden"]
    resume, latest, recent_albums, new_albums, podcasts = await asyncio.gather(
        safe(clients.jf_resume(), []), safe(clients.jf_latest(), []),
        safe(clients.nd_albums("recent"), []), safe(clients.nd_albums("newest"), []),
        safe(clients.abs_recent(), []),
    )
    if "watch" in hidden:   # a tab turned off for this account doesn't leak through the home page
        resume, latest = [], []
    if "listen" in hidden:
        recent_albums, new_albums, podcasts = [], [], []
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
async def search(q: str, request: Request):
    hidden = request.state.user["hidden"]
    q = q.strip()
    if len(q) < 2:
        return {"jellyfin": [], "navidrome": [], "catalog": []}
    jf, nd = await asyncio.gather(safe(clients.jf_search(q), []), safe(clients.nd_search(q), []))
    ql = q.lower()
    cat = [e for e in CATALOG["entries"]
           if ql in " ".join([e["name"], e.get("description", ""), " ".join(e.get("topics", [])),
                              e.get("category", "")]).lower()]
    return {"jellyfin": [] if "watch" in hidden else jf, "navidrome": [] if "listen" in hidden else nd, "catalog": cat[:30]}


# ---- small key/value store (YouTube channel ids, sport channels, settings…)
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
    import re as _re
    if path not in {"report", "reports", "queues", "health"} and not _re.fullmatch(r"reports/[A-Za-z0-9_.-]+", path) or ".." in path:
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


# ---- tap an album = play it right away in the hub (no Navidrome login: the hub talks to it server-side)
def _safe_id(v: str) -> str:
    if not v or not v.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(404)
    return v


@app.get("/api/nd/album/{album_id}")
async def nd_album_tracks(album_id: str):
    try:
        data = await clients.nd_call("getAlbum", id=_safe_id(album_id))
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "music server not reachable"}, status_code=503)
    a = (data or {}).get("album", {})
    songs = [{"id": s["id"], "title": s.get("title", ""), "artist": s.get("artist", a.get("artist", "")),
              "album": s.get("album", a.get("name", "")), "duration": s.get("duration", 0),
              "image": f"/api/img/nd/{s.get('coverArt', album_id)}"} for s in a.get("song", [])]
    return {"id": album_id, "name": a.get("name", ""), "artist": a.get("artist", ""), "songs": songs}


@app.get("/api/nd/album/{album_id}/play")
async def nd_album_play(album_id: str, request: Request, n: float = 0.0):
    """Streams song number floor(n * count) of the album, so a tap can start the sound right away."""
    try:
        data = await clients.nd_call("getAlbum", id=_safe_id(album_id))
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "music server not reachable")
    songs = (data or {}).get("album", {}).get("song", [])
    if not songs:
        raise HTTPException(404, "no songs")
    return await nd_stream(songs[min(len(songs) - 1, max(0, int(n * len(songs))))]["id"], request)


@app.get("/api/nd/stream/{song_id}")
async def nd_stream(song_id: str, request: Request):
    """Proxies the original audio file, with byte ranges (iPhone Safari needs them to play and seek)."""
    headers = {"Range": request.headers["range"]} if "range" in request.headers else {}
    req = clients.client.build_request("GET", f"{clients.ND_URL}/rest/stream", headers=headers,
                                       params=clients._nd_params(id=_safe_id(song_id), format="raw"),
                                       timeout=httpx.Timeout(20.0, read=None))
    try:
        r = await clients.client.send(req, stream=True)
    except httpx.HTTPError:
        raise HTTPException(503, "music server not reachable")
    keep = {k: r.headers[k] for k in ("content-type", "content-length", "content-range", "accept-ranges") if k in r.headers}
    keep.setdefault("accept-ranges", "bytes")
    return StreamingResponse(r.aiter_raw(), status_code=r.status_code, headers=keep, background=BackgroundTask(r.aclose))


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
