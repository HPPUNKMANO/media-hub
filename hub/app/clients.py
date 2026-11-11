"""Server-side clients for Jellyfin, Navidrome (Subsonic API), Audiobookshelf and the organizer.
API keys never leave the server; the browser only talks to the Hub."""
from __future__ import annotations

import hashlib
import os
import secrets

import httpx

E = os.environ.get
JF_URL = E("JELLYFIN_URL", "http://jellyfin:8096")
JF_KEY = E("JELLYFIN_API_KEY", "").strip()
JF_USER = E("JELLYFIN_USER", "").strip()
ND_URL = E("NAVIDROME_URL", "http://navidrome:4533")
ND_USER = E("NAVIDROME_USER", "").strip()
ND_PASS = E("NAVIDROME_PASSWORD", "").strip()
ABS_URL = E("ABS_URL", "http://audiobookshelf:80")
ABS_TOKEN = E("ABS_API_TOKEN", "").strip()
ORG_URL = E("ORGANIZER_URL", "http://organizer:8000")

client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0), follow_redirects=True)


# ---------------------------------------------------------------- Jellyfin
_jf_user_id: str | None = None


def _jf_headers():
    return {"Authorization": f'MediaBrowser Token="{JF_KEY}"'}


async def jf_user_id() -> str | None:
    """Resolve JELLYFIN_USER (name) to an id; falls back to the first administrator."""
    global _jf_user_id
    if _jf_user_id or not JF_KEY:
        return _jf_user_id
    r = await client.get(f"{JF_URL}/Users", headers=_jf_headers())
    r.raise_for_status()
    users = r.json()
    match = [u for u in users if u.get("Name", "").lower() == JF_USER.lower()] if JF_USER else []
    if not match:
        match = [u for u in users if u.get("Policy", {}).get("IsAdministrator")] or users
    _jf_user_id = match[0]["Id"] if match else None
    return _jf_user_id


def _jf_item(i: dict) -> dict:
    kind = i.get("Type")
    title = i.get("Name", "")
    subtitle = str(i.get("ProductionYear") or "")
    if kind == "Episode":
        title = i.get("SeriesName") or title
        subtitle = f"S{i.get('ParentIndexNumber', 0):02d}E{i.get('IndexNumber', 0):02d} · {i.get('Name', '')}"
    img_id = i["Id"]
    if kind == "Episode" and i.get("SeriesId") and not i.get("ImageTags", {}).get("Primary"):
        img_id = i["SeriesId"]
    pos = i.get("UserData", {}).get("PlayedPercentage")
    return {
        "id": i["Id"], "title": title, "subtitle": subtitle, "type": kind,
        "image": f"/api/img/jf/{img_id}",
        "progress": round(pos) if pos else None,
        "backdrop": f"/api/img/jfb/{i.get('SeriesId') if kind == 'Episode' and i.get('SeriesId') else i['Id']}"
                    if i.get("BackdropImageTags") or i.get("ParentBackdropImageTags") else "",
        "overview": (i.get("Overview") or "")[:280],
        "genres": (i.get("Genres") or [])[:3],
        "runtime": round(i["RunTimeTicks"] / 600_000_000) if i.get("RunTimeTicks") else None,
        "link": f"/web/#/details?id={i['Id']}",
        "service": "jellyfin",
    }


async def jf_get(path: str, **params):
    uid = await jf_user_id()
    if not uid:
        return []
    r = await client.get(f"{JF_URL}{path.format(uid=uid)}", headers=_jf_headers(), params=params)
    r.raise_for_status()
    return r.json()


async def jf_resume(limit=12):
    data = await jf_get("/Users/{uid}/Items/Resume", Limit=limit, MediaTypes="Video",
                        Fields="PrimaryImageAspectRatio,Overview,Genres,BackdropImageTags,ParentBackdropImageTags")
    return [_jf_item(i) for i in data.get("Items", [])] if data else []


async def jf_latest(limit=16):
    data = await jf_get("/Users/{uid}/Items/Latest", Limit=limit, IncludeItemTypes="Movie,Series,Episode,Video",
                        GroupItems="true", Fields="Overview,Genres,BackdropImageTags,ParentBackdropImageTags")
    return [_jf_item(i) for i in data] if data else []


async def jf_items(kinds="Movie", limit=300):
    data = await jf_get("/Users/{uid}/Items", Recursive="true", IncludeItemTypes=kinds, Limit=limit,
                        SortBy="DateCreated,SortName", SortOrder="Descending",
                        Fields="Overview,Genres,BackdropImageTags,ParentBackdropImageTags")
    return [_jf_item(i) for i in (data or {}).get("Items", [])]


async def jf_libraries():
    data = await jf_get("/Users/{uid}/Views")
    return [{"id": v["Id"], "title": v["Name"], "type": v.get("CollectionType", ""),
             "image": f"/api/img/jf/{v['Id']}", "link": f"/web/#/list.html?parentId={v['Id']}",
             "service": "jellyfin"} for v in (data or {}).get("Items", [])]


async def jf_search(q: str, limit=20):
    data = await jf_get("/Users/{uid}/Items", searchTerm=q, Recursive="true", Limit=limit,
                        IncludeItemTypes="Movie,Series,Episode,Video,MusicVideo")
    return [_jf_item(i) for i in (data or {}).get("Items", [])]


async def jf_image(item_id: str):
    # recent Jellyfin versions require auth even for artwork
    return await client.get(f"{JF_URL}/Items/{item_id}/Images/Primary", headers=_jf_headers(),
                            params={"maxHeight": 400, "quality": 85})


async def jf_backdrop(item_id: str):
    return await client.get(f"{JF_URL}/Items/{item_id}/Images/Backdrop/0", headers=_jf_headers(),
                            params={"maxWidth": 1920, "quality": 82})


# ---------------------------------------------------------------- Navidrome
def _nd_params(**extra):
    salt = secrets.token_hex(6)
    return {"u": ND_USER, "t": hashlib.md5((ND_PASS + salt).encode()).hexdigest(), "s": salt,
            "v": "1.16.1", "c": "media-hub", "f": "json", **extra}


async def nd_call(method: str, **params) -> dict:
    if not (ND_USER and ND_PASS):
        return {}
    r = await client.get(f"{ND_URL}/rest/{method}", params=_nd_params(**params))
    r.raise_for_status()
    data = r.json().get("subsonic-response", {})
    if data.get("status") != "ok":
        raise RuntimeError(data.get("error", {}).get("message", "navidrome error"))
    return data


def _nd_album(a: dict) -> dict:
    return {"id": a["id"], "title": a.get("name") or a.get("album", ""), "subtitle": a.get("artist", ""),
            "type": "Album", "image": f"/api/img/nd/{a.get('coverArt', a['id'])}",
            "link": f"/app/#/album/{a['id']}/show", "service": "navidrome"}


async def nd_albums(kind: str, size=16):
    data = await nd_call("getAlbumList2", type=kind, size=size)
    return [_nd_album(a) for a in data.get("albumList2", {}).get("album", [])] if data else []


async def nd_search(q: str):
    data = await nd_call("search3", query=q, albumCount=10, artistCount=5, songCount=10)
    res = data.get("searchResult3", {}) if data else {}
    out = [_nd_album(a) for a in res.get("album", [])]
    out += [{"id": a["id"], "title": a["name"], "subtitle": "Artist", "type": "Artist",
             "image": f"/api/img/nd/{a.get('coverArt', a['id'])}", "link": f"/app/#/artist/{a['id']}/show",
             "service": "navidrome"} for a in res.get("artist", [])]
    out += [{"id": s["id"], "title": s["title"], "subtitle": f"{s.get('artist', '')} · {s.get('album', '')}",
             "type": "Song", "image": f"/api/img/nd/{s.get('coverArt', s.get('albumId', s['id']))}",
             "link": f"/app/#/album/{s.get('albumId', '')}/show", "service": "navidrome"} for s in res.get("song", [])]
    return out


async def nd_radios():
    data = await nd_call("getInternetRadioStations")
    return data.get("internetRadioStations", {}).get("internetRadioStation", []) if data else []


async def nd_image(cover_id: str):
    return await client.get(f"{ND_URL}/rest/getCoverArt", params=_nd_params(id=cover_id, size=400))


# ---------------------------------------------------------------- Audiobookshelf
async def abs_recent(limit=12):
    if not ABS_TOKEN:
        return []
    h = {"Authorization": f"Bearer {ABS_TOKEN}"}
    r = await client.get(f"{ABS_URL}/api/libraries", headers=h)
    r.raise_for_status()
    out = []
    for lib in r.json().get("libraries", []):
        if lib.get("mediaType") != "podcast":
            continue
        rr = await client.get(f"{ABS_URL}/api/libraries/{lib['id']}/recent-episodes", headers=h, params={"limit": limit})
        if rr.status_code != 200:
            continue
        for ep in rr.json().get("episodes", []):
            out.append({"id": ep.get("id"), "title": ep.get("title", ""),
                        "subtitle": ep.get("podcast", {}).get("metadata", {}).get("title", ""), "type": "Episode",
                        "image": f"/api/img/abs/{ep.get('libraryItemId')}",
                        "link": f"/item/{ep.get('libraryItemId')}", "service": "audiobookshelf"})
    return out[:limit]


async def abs_image(item_id: str):
    return await client.get(f"{ABS_URL}/api/items/{item_id}/cover", headers={"Authorization": f"Bearer {ABS_TOKEN}"},
                            params={"width": 400})


# ---------------------------------------------------------------- status
async def ping(url: str) -> bool:
    try:
        r = await client.get(url, timeout=3.0)
        return r.status_code < 500
    except httpx.HTTPError:
        return False


async def status():
    return {
        "jellyfin": {"up": await ping(f"{JF_URL}/health"), "configured": bool(JF_KEY)},
        "navidrome": {"up": await ping(f"{ND_URL}/ping"), "configured": bool(ND_USER and ND_PASS)},
        "audiobookshelf": {"up": await ping(f"{ABS_URL}/healthcheck"), "configured": bool(ABS_TOKEN)},
        "organizer": {"up": await ping(f"{ORG_URL}/health"), "configured": True},
    }
