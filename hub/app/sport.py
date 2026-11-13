"""Sport: live scores + the big matches (ESPN's public scoreboards, no key) and the free, official live
streams of the sport channels on YouTube (padel, table tennis, darts, basketball, tennis, football, F1, cycling),
played inside the hub. Nothing here is a pirate stream: big paid matches show score + time only.

Ranking: every match gets a weight (competition + how famous the teams/players are), so the big
matches come first. Scores are re-read every 90 s for today, every hour for other days.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from . import youtube

router = APIRouter()
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{}/scoreboard"

SPORTS = {"foot": "Foot", "basket": "Basket", "tennis": "Tennis", "rugby": "Rugby", "hand": "Handball",
          "volley": "Volley", "pingpong": "Ping-pong", "darts": "Fléchettes", "padel": "Padel", "f1": "F1",
          "moteur": "Moto & auto", "velo": "Cyclisme", "combat": "Boxe & MMA", "nfl": "Foot US", "hockey": "Hockey",
          "athle": "Athlé & natation", "hiver": "Ski & hiver", "golf": "Golf", "autre": "Autres"}

# (ESPN path, sport, display name, weight 1-10)
LEAGUES = [
    ("soccer/fifa.world", "foot", "Coupe du monde", 10), ("soccer/uefa.euro", "foot", "Euro", 10),
    ("soccer/uefa.champions", "foot", "Ligue des champions", 9), ("soccer/fra.1", "foot", "Ligue 1", 8),
    ("soccer/eng.1", "foot", "Premier League", 8), ("soccer/esp.1", "foot", "Liga", 8),
    ("soccer/ita.1", "foot", "Serie A", 7), ("soccer/ger.1", "foot", "Bundesliga", 7),
    ("soccer/uefa.europa", "foot", "Ligue Europa", 6), ("soccer/uefa.nations", "foot", "Ligue des nations", 6),
    ("soccer/fifa.worldq.uefa", "foot", "Qualif. Coupe du monde", 6), ("soccer/uefa.euroq", "foot", "Qualif. Euro", 6),
    ("soccer/fra.coupe_de_france", "foot", "Coupe de France", 4), ("soccer/uefa.europa.conf", "foot", "Conference League", 4), ("soccer/fifa.friendly", "foot", "Match amical", 3),
    ("basketball/nba", "basket", "NBA", 7),
    ("rugby/164205", "rugby", "Coupe du monde de rugby", 10), ("rugby/180659", "rugby", "Tournoi des Six Nations", 9),
    ("rugby/289234", "rugby", "Test-match", 7), ("rugby/270559", "rugby", "Top 14", 7),
    ("rugby/271937", "rugby", "Champions Cup", 6), ("football/nfl", "nfl", "NFL", 5), ("hockey/nhl", "hockey", "NHL", 4),
    ("tennis/atp", "tennis", "ATP", 6), ("tennis/wta", "tennis", "WTA", 5),
]
BIG_TEAMS = {
    # clubs
    "paris saint-germain", "marseille", "lyon", "monaco", "lille", "lens", "nice", "real madrid", "barcelona",
    "atletico madrid", "manchester city", "manchester united", "liverpool", "arsenal", "chelsea", "tottenham hotspur",
    "bayern munich", "borussia dortmund", "bayer leverkusen", "juventus", "internazionale", "ac milan", "napoli",
    # national teams
    "france", "spain", "england", "germany", "portugal", "brazil", "argentina", "italy", "netherlands", "belgium",
    # NBA
    "los angeles lakers", "golden state warriors", "boston celtics", "san antonio spurs", "new york knicks",
    "stade toulousain", "toulouse", "racing 92", "stade rochelais", "la rochelle", "rc toulon", "toulon",
    "union bordeaux-begles", "bordeaux-begles", "new zealand", "south africa", "ireland", "kansas city chiefs",
    "denver nuggets", "oklahoma city thunder", "milwaukee bucks", "philadelphia 76ers", "dallas mavericks",
}
TENNIS_BIG = re.compile(r"australian open|roland|french open|wimbledon|us open|finals|masters|paris|monte|olymp|davis|bnp", re.I)

# Official channels that stream full matches for free (lives found automatically, every 5 min)
LIVE_CHANNELS = [
    ("@PremierPadelOfficial", "padel"), ("@PadelFIP", "padel"),
    ("@WTTGlobal", "pingpong"), ("@ITTFWorld", "pingpong"),
    ("@MODUSSuperSeries", "darts"), ("@WDFDarts", "darts"), ("@OfficialPDC", "darts"),
    ("@basketballCL", "basket"), ("@LNBofficiel", "basket"), ("@FIBA3x3", "basket"), ("@EuroLeague", "basket"),
    ("@KingsLeagueFrance", "foot"), ("@FFF", "foot"), ("@DAZNFootball", "foot"), ("@Ligue1", "foot"),
    ("@TennisTV", "tennis"), ("@ATPTour", "tennis"), ("@WTA", "tennis"),
    ("@Formula1", "f1"), ("@F1Academy", "f1"),
    ("@letourdefrance", "velo"), ("@giroditalia", "velo"), ("@GCNRacing", "velo"),   # ASO (Tour, Paris-Roubaix…), RCS (Giro, Strade Bianche…), GCN race coverage
    ("@FranceRugby", "rugby"), ("@ehfeuro", "hand"), ("@StarHandball", "hand"), ("@WorldAthletics", "athle"),
    ("@UFC", "combat"), ("@HexagoneMMA", "combat"), ("@NFL", "nfl"), ("@RedBull", "autre"), ("@LEquipe", "autre"),
]
# What a TV programme is about, from its title + category (French TV guide)
SPORT_WORDS = [
    ("foot", r"football(?! am)|ligue 1|ligue des champions|ligue europa|coupe de france|premier league|liga\b|serie a|bundesliga|\bfoot\b|euro 20|mondial"),
    ("rugby", r"rugby|top 14|six nations|pro d2"), ("basket", r"basket|nba|euroleague|betclic elite"),
    ("tennis", r"tennis(?! de table)|roland|atp|wta|wimbledon|open d'australie|us open|coupe davis"),
    ("hand", r"handball|hand\b|starligue"), ("volley", r"volley"), ("pingpong", r"tennis de table|ping"),
    ("darts", r"fl[eé]chettes|darts"), ("padel", r"padel"), ("f1", r"formule 1|\bf1\b|grand prix de"),
    ("moteur", r"moto|motogp|rallye|automobile|endurance|nascar|indycar|dakar|wrc|superbike"),
    ("velo", r"cyclisme|tour de|v[eé]lo|paris-roubaix|giro|vuelta|bmx|vtt"), ("combat", r"boxe|mma|ufc|judo|lutte|karat|catch"),
    ("nfl", r"football am[eé]ricain|nfl|super bowl"), ("hockey", r"hockey|nhl"),
    ("athle", r"athl[eé]tisme|marathon|natation|triathlon"), ("hiver", r"ski|biathlon|patinage|snowboard|bobsleigh"),
    ("golf", r"golf"),
]
SPORT_RE = [(k, re.compile(w, re.I)) for k, w in SPORT_WORDS]
# youth / amateur: not "real matches" (user wants pros only)
YOUTH = re.compile(r"\bU-?\d{2}\b|\bU\d{2}\b|junior|juniors|jeunes|youth|espoirs|cadets|amateur|\bgirls\b|\bboys\b|national 3|\bN3\b|r[eé]gional", re.I)
TNT = re.compile(r"^(tf1|france [2345]|m6|w9|tmc|tfx|arte|l['’]?[eé]quipe|la cha[iî]ne l['’]?[eé]quipe|rmc story|rmc d[eé]couverte|cstar|gulli|6ter)$", re.I)   # free-to-air
# French channels whose guide we read for live sport (the others are films, news…)
EPG_CHANNELS = re.compile(r"^(tf1|france [2345]|m6|w9|tmc|tfx|l['’]?[eé]quipe|la cha[iî]ne l['’]?[eé]quipe|rmc story|rmc d[eé]couverte|"
                          r"canal\+( sport| foot| sport 360| ligue 1.*| premier league)?|bein sports [123]|rmc sport [12]|eurosport [12]|"
                          r"dazn 1|sport en france|automoto.*|arte|cstar|gulli|equidia|infosport\+?)$", re.I)
# Live TV channels (from the hub's own TV list) that show sport — matched by name
TV_SPORT = re.compile(r"^((la chaîne )?l['’]?[eé]quipe|sport en france|w-sport|automoto|france 2|france 3|rmc story|dazn darts.*|dazn combat|"
                      r"eurovision sport|red bull tv|fifa\+ french|fifa\+|tennis channel)$", re.I)

_score_cache: dict[tuple, tuple[float, list]] = {}
_live: dict = {"t": 0.0, "data": None}
_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _espn(path: str, day: str | None) -> list[dict]:
    key = (path, day)
    hit = _score_cache.get(key)
    today = _now().strftime("%Y%m%d")
    ttl = 90 if day in (None, today) else 3600
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        r = await youtube.http.get(ESPN.format(path), params={"dates": day} if day else None)
        events = r.json().get("events", []) if r.status_code == 200 else []
    except Exception:  # noqa: BLE001 - one league down must not break the page
        return hit[1] if hit else []
    _score_cache[key] = (time.time(), events)
    return events


def _status(st: dict) -> tuple[str, str]:
    t = st.get("type", {})
    state = t.get("state", "pre")
    if state == "in":
        if t.get("name") == "STATUS_HALFTIME":
            return "in", "Mi-temps"
        return "in", st.get("displayClock") or t.get("shortDetail") or "en cours"
    return state, t.get("shortDetail", "")


def _fr(text: str) -> str:
    """ESPN's '3rd', 'Halftime', 'End of 2nd' in French."""
    text = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1e", text or "")
    return text.replace("Halftime", "Mi-temps").replace("End of", "Fin du").replace("OT", "Prol.")


def _team_match(e: dict, sport: str, league: str, weight: int) -> dict | None:
    comp = (e.get("competitions") or [{}])[0]
    teams = comp.get("competitors") or []
    if len(teams) != 2:
        return None
    home = next((t for t in teams if t.get("homeAway") == "home"), teams[0])
    away = next((t for t in teams if t is not home), teams[1])
    side = lambda t: {"name": t["team"].get("shortDisplayName") or t["team"].get("displayName", ""),   # noqa: E731
                      "full": t["team"].get("displayName", ""), "logo": t["team"].get("logo", ""), "score": t.get("score", "")}
    state, detail = _status(e.get("status") or comp.get("status") or {})
    if sport == "basket" and state == "in":   # "5:21 - 3rd" says more than the clock alone
        detail = _fr((e.get("status") or {}).get("type", {}).get("shortDetail", detail))
    big = sum(t["team"].get("displayName", "").lower() in BIG_TEAMS for t in teams)
    return {"id": e.get("id"), "sport": sport, "league": league, "date": e.get("date"), "state": state, "detail": detail,
            "home": side(home), "away": side(away), "score": weight * 10 + big * 18, "big": weight >= 5 or big >= 1}


def _tennis(e: dict, league: str, weight: int) -> list[dict]:
    """A tennis 'event' is a tournament: we list its singles matches of the day (live first)."""
    tourney = e.get("name", "")
    w = weight + (4 if TENNIS_BIG.search(tourney) else 0)
    out = []
    for g in e.get("groupings", []):
        if "singles" not in g.get("grouping", {}).get("slug", ""):
            continue
        for c in g.get("competitions", []):
            ps = c.get("competitors") or []
            if len(ps) != 2:
                continue
            state, detail = _status(c.get("status", {}))
            if state == "in":
                detail = _fr(detail) + (" set" if re.fullmatch(r"\d+e", _fr(detail)) else "")
            d = c.get("date") or c.get("startDate") or ""
            age = _now() - datetime.fromisoformat(d.replace("Z", "+00:00")) if d else timedelta(0)
            if (state == "post" and age > timedelta(hours=20)) or (state == "in" and age > timedelta(hours=8)):
                continue
            side = lambda p: {"name": p.get("athlete", {}).get("shortName", ""), "full": p.get("athlete", {}).get("displayName", ""),   # noqa: E731
                              "logo": p.get("athlete", {}).get("flag", {}).get("href", ""),
                              "score": " ".join(str(int(s.get("value", 0))) for s in p.get("linescores", []))}
            out.append({"id": c.get("id"), "sport": "tennis", "league": f"{league} · {tourney}", "date": d, "state": state,
                        "detail": detail, "home": side(ps[0]), "away": side(ps[1]), "score": w * 10, "big": w >= 8})
    return out


async def _f1() -> list[dict]:
    """The current/next Grand Prix and its sessions (practice, qualifying, race)."""
    out = []
    for e in await _espn("racing/f1", None):
        for c in e.get("competitions", []):
            kind = (c.get("type") or {}).get("abbreviation", "")
            state, detail = _status(c.get("status", {}))
            podium = sorted((p for p in c.get("competitors", []) if p.get("order")), key=lambda p: p["order"])[:3]
            out.append({"id": f"f1-{e.get('id')}-{kind}", "sport": "f1", "league": "Formule 1", "date": c.get("date"),
                        "state": state, "detail": detail, "gp": e.get("name", ""), "session": {"FP1": "Essais 1", "FP2": "Essais 2",
                        "FP3": "Essais 3", "Qual": "Qualifications", "Race": "Course", "SS": "Sprint qualif.", "Sprint": "Sprint"}.get(kind, kind),
                        "podium": [p.get("athlete", {}).get("displayName", "") for p in podium],
                        "score": 95 if kind == "Race" else 80 if kind == "Qual" else 60, "big": kind in ("Race", "Qual", "Sprint")})
    return out


async def scores() -> list[dict]:
    now = _now()
    days = [(now + timedelta(days=d)).strftime("%Y%m%d") for d in range(-1, 6)]
    jobs, meta = [], []
    for path, sport, name, w in LEAGUES:
        for day in (days if sport != "tennis" else [None]):
            jobs.append(_espn(path, day))
            meta.append((path, sport, name, w))
    results = await asyncio.gather(*jobs)
    out, seen = [], set()
    for (path, sport, name, w), events in zip(meta, results):
        for e in events:
            items = _tennis(e, name, w) if sport == "tennis" else [_team_match(e, sport, name, w)]
            for m in items:
                if m:
                    m["path"] = path
            for m in items:
                if m and (m["sport"], m["id"]) not in seen:
                    seen.add((m["sport"], m["id"]))
                    out.append(m)
    out += await _f1()
    # keep: live, finished in the last 20 h, and upcoming in the next 6 days
    keep = []
    for m in out:
        try:
            d = datetime.fromisoformat((m["date"] or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if m["state"] == "in" or (m["state"] == "post" and now - d < timedelta(hours=20)) or \
                (m["state"] == "pre" and timedelta(hours=-3) < d - now < timedelta(days=6)):
            keep.append(m)
    return keep


# ----------------------------------------------------------------- YouTube lives
# One request per channel: the channel's "Live" tab already says which streams are live (red LIVE badge)
# and when the planned ones start. Opening every video page instead got the hub rate-limited by YouTube.
PLANNED = re.compile(r"Planifi\w* pour le (\d\d)/(\d\d)/(\d{4}),? (?:à )?(\d\d):(\d\d)")
_sem = asyncio.Semaphore(4)


def _parse_streams(text: str) -> list[dict]:
    from zoneinfo import ZoneInfo
    out = []
    for part in text.split('"lockupViewModel":{')[1:13]:
        vid = re.search(r'"contentId":"([\w-]{11})"', part)
        title = re.search(r'"title":\{"content":"((?:[^"\\]|\\.)*)"', part)
        if not vid or not title:
            continue
        try:
            name = json.loads(f'"{title.group(1)}"')
        except ValueError:
            name = title.group(1)
        head = part[:12000]
        live = "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE" in head
        when = PLANNED.search(head)
        start = ""
        if when:
            d, m, y, hh, mm = map(int, when.groups())
            start = datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc).isoformat()   # YouTube shows anonymous visitors Pacific time
        if (live or start) and not YOUTH.search(name):
            out.append({"id": vid.group(1), "title": name, "live": live, "start": start, "upcoming": not live})
    return out


async def _channel_lives(ch: dict) -> list[dict]:
    """Every stream live now on this channel (big tournaments run several courts at once) + planned ones."""
    async with _sem:
        try:
            r = await youtube.http.get(f"https://www.youtube.com/channel/{ch['id']}/streams")
        except Exception:  # noqa: BLE001
            return []
    if r.status_code != 200:
        return []
    return [{**i, "sport": ch["cat"], "channel": ch["title"], "avatar": ch.get("avatar", ""),
             "thumb": f"https://i.ytimg.com/vi/{i['id']}/hqdefault.jpg"} for i in _parse_streams(r.text)]


_embed: dict[str, tuple[float, bool]] = {}
_esem = asyncio.Semaphore(6)


async def embeddable(vid: str) -> bool:
    """YouTube's oEmbed answers 401/403 when the channel turned off playing its videos on other sites."""
    hit = _embed.get(vid)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    async with _esem:
        try:
            r = await youtube.http.get("https://www.youtube.com/oembed",
                                       params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
            ok = r.status_code not in (401, 403)
        except Exception:  # noqa: BLE001
            return True
    _embed[vid] = (time.time(), ok)
    return ok


async def _mark(items: list[dict]) -> list[dict]:
    flags = await asyncio.gather(*(embeddable(i["id"]) for i in items))
    return [{**i, "embed": f} for i, f in zip(items, flags)]


async def channels() -> list[dict]:
    return await youtube._channels("sport_channels_v3", LIVE_CHANNELS)


async def lives() -> dict:
    async with _lock:   # one refresh at a time, whoever asks
        if _live["data"] is None or time.time() - _live["t"] > 240:
            chans = await channels()
            lists = await asyncio.gather(*(_channel_lives(c) for c in chans))
            items = [i for l in lists for i in l]
            live = await _mark([i for i in items if i["live"]])
            live.sort(key=lambda i: not i["embed"])   # the ones that play inside the hub first
            soon = (_now() - timedelta(hours=1)).isoformat()   # a planned stream that should have started an hour ago is gone
            upcoming = sorted([i for i in items if i["upcoming"] and i["start"] >= soon], key=lambda i: i["start"])
            _live.update(t=time.time(), data={"live": live, "upcoming": upcoming[:20]})
    return _live["data"]


async def replays(sport: str) -> list[dict]:
    chans = [c for c in await channels() if not sport or c["cat"] == sport]
    lists = await asyncio.gather(*(youtube.channel_videos(c["id"]) for c in chans))
    vids = [{**v, "sport": c["cat"]} for c, l in zip(chans, lists) for v in l if not v["short"]]
    return await _mark(sorted(vids, key=lambda v: v["published"], reverse=True)[:24])


def tv_channels() -> list[dict]:
    from . import tv
    out, seen = [], set()
    for c in sorted(tv.channels(), key=lambda c: not c["group"].startswith("TNT")):   # your Freebox first
        key = re.sub(r"^la chaîne ", "", c["name"].lower())
        if (c["group"] == "Sport" or c["group"].startswith("TNT")) and TV_SPORT.match(c["name"]) and key not in seen:
            seen.add(key)
            out.append({"id": c["id"], "name": c["name"], "logo": c["logo"]})
    return out


EPG_URL = "https://xmltvfr.fr/xmltv/xmltv_fr.xml.gz"
_epg: dict = {"t": 0.0, "items": []}


def _web(channel: str) -> str:
    """TF1 and M6 groups refuse to be relayed by the Freebox; Freebox subscribers watch them free in the Free TV app."""
    c = _plain(channel)
    if c in ("tf1", "tmc", "tfx", "tf1 series films", "tf1 series-films", "lci", "m6", "w9", "6ter", "gulli"):
        return "https://tv.free.fr/home"
    return ""


def _guess(text: str) -> str:
    return next((k for k, r in SPORT_RE if r.search(text)), "autre")


def _parse_epg(raw: bytes) -> list[dict]:
    import gzip
    import unicodedata
    import xml.etree.ElementTree as ET
    root = ET.fromstring(gzip.decompress(raw))
    names = {c.get("id"): (c.findtext("display-name") or "") for c in root.findall("channel")}
    norm = lambda t: unicodedata.normalize("NFKD", t.replace("’", "'")).encode("ascii", "ignore").decode().lower().replace("la chaine ", "").strip()   # noqa: E731
    from . import tv
    hub = {}
    for c in tv.channels():
        if c["group"].startswith("TNT") or c["group"] == "Sport":
            hub.setdefault(norm(c["name"]), c["id"])
    now = _now()
    out = []
    for p in root.findall("programme"):
        name = names.get(p.get("channel"), "")
        if not EPG_CHANNELS.match(name):
            continue
        cats = " ".join(c.text or "" for c in p.findall("category")).lower()
        title = p.findtext("title") or ""
        if "sport" not in cats and not any(r.search(cats) for _, r in SPORT_RE):
            continue
        if re.search(r"magazine|mag sport|journal|talk|d[eé]bat|jeu", cats) or re.search(r"\bmag\b|magazine|l'[eé]quipe du soir|week-end|late|club|tous sports|direct auto|jt", title, re.I):
            continue
        try:
            start = datetime.strptime(p.get("start", ""), "%Y%m%d%H%M%S %z")
            stop = datetime.strptime(p.get("stop", ""), "%Y%m%d%H%M%S %z")
        except ValueError:
            continue
        if stop < now or start > now + timedelta(hours=36) or (stop - start) < timedelta(minutes=25):
            continue
        sub = p.findtext("sub-title") or ""
        desc = (p.findtext("desc") or "")[:220]
        if YOUTH.search(f"{title} {sub}"):
            continue
        hub_id = hub.get(norm(name))
        out.append({"channel": name, "title": title, "sub": sub, "desc": desc, "start": start.astimezone(timezone.utc).isoformat(),
                    "stop": stop.astimezone(timezone.utc).isoformat(), "sport": _guess(f"{title} {sub} {cats}"),
                    "tv_id": hub_id, "free": hub_id is not None, "tnt": bool(TNT.match(name)), "live": start <= now < stop,
                    "web": _web(name)})
    return sorted(out, key=lambda x: x["start"])


async def tv_guide() -> list[dict]:
    """Downloaded every 6 h (French guide, ~9 MB) and kept in /data, read again every 10 min for 'now'."""
    from .main import DATA_DIR
    f = DATA_DIR / "epg_fr.xml.gz"
    if not f.exists() or time.time() - f.stat().st_mtime > 6 * 3600:
        try:
            r = await youtube.http.get(EPG_URL, timeout=60)
            if r.status_code == 200 and len(r.content) > 100_000:
                f.write_bytes(r.content)
                _epg["t"] = 0
        except Exception:  # noqa: BLE001 - keep the old guide
            pass
    if f.exists() and time.time() - _epg["t"] > 600:
        try:
            _epg.update(t=time.time(), items=await asyncio.to_thread(_parse_epg, f.read_bytes()))
        except Exception:  # noqa: BLE001
            pass
    now = _now().isoformat()
    for i in _epg["items"]:
        i["live"] = i["start"] <= now < i["stop"]
    return [i for i in _epg["items"] if i["stop"] > now]


async def _warm() -> None:
    while True:
        try:
            await asyncio.gather(scores(), lives(), tv_guide())
        except Exception:  # noqa: BLE001 - try again next round
            pass
        await asyncio.sleep(240)


def start() -> None:
    asyncio.get_event_loop().create_task(_warm())


@router.get("/api/sport")
async def sport(s: str = ""):
    s = s if s in SPORTS else ""
    sc, lv, rp, guide = await asyncio.gather(scores(), lives(), replays(s), tv_guide())
    guide_all = guide
    if s:
        sc = [m for m in sc if m["sport"] == s]
    live_scores = sorted((m for m in sc if m["state"] == "in"), key=lambda m: -m["score"])
    soon = sorted((m for m in sc if m["state"] == "pre"), key=lambda m: m["date"])
    from zoneinfo import ZoneInfo
    paris = lambda m: datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Paris")).date()   # noqa: E731
    friendlies = sorted((m for m in sc if m["league"] == "Match amical" and m["state"] != "post"), key=lambda m: m["date"])
    soon = [m for m in soon if m["league"] != "Match amical"]
    big, per_day = [], {}
    for m in sorted((m for m in soon if m["big"]), key=lambda m: (paris(m), -m["score"], m["date"])):
        n = per_day[paris(m)] = per_day.get(paris(m), 0) + 1
        if n <= 6 or m["score"] >= 90:   # the 6 biggest of each day (+ any huge one)
            big.append(m)
    results = sorted((m for m in sc if m["state"] == "post"), key=lambda m: (-m["score"], m["date"]))
    yt_live = [v for v in lv["live"] if not s or v["sport"] == s]
    guide = [g for g in guide if not s or g["sport"] == s]
    counts = {}
    for k in [v["sport"] for v in lv["live"]] + [m["sport"] for m in sc if m["state"] == "in"] + [g["sport"] for g in guide if g["live"]]:
        counts[k] = counts.get(k, 0) + 1
    yt_up = [v for v in lv["upcoming"] if not s or v["sport"] == s]
    live_scores = [_where(m, guide_all) for m in live_scores]
    big = [_where(m, guide_all) for m in big]
    return {"sports": SPORTS, "live": live_scores, "big": big[:40], "results": results[:30],
            "streams": yt_live, "upcoming_streams": yt_up[:12], "replays": rp, "tv": tv_channels(),
            "friendlies": [_where(m, guide_all) for m in friendlies[:30]],
            "tv_now": [g for g in guide if g["live"]], "tv_next": [g for g in guide if not g["live"]][:30], "live_counts": counts}


@router.get("/api/sport/live")
async def sport_live():
    """Small and fast: what is live right now (menu badge + home banner)."""
    lv = await lives()
    sc = [m for m in await scores() if m["state"] == "in" and m["big"]]
    guide = [g for g in await tv_guide() if g["live"]]
    return {"streams": lv["live"], "big_live": sorted(sc, key=lambda m: -m["score"])[:5],
            "tv_free": [g for g in guide if g["free"]], "tv_paid": [g for g in guide if not g["free"]]}


SPORT_NEWS = [("lequipe", "L'Équipe", "Sport", "https://dwh.lequipe.fr/api/edito/rss?path=/"),
              ("rmcsport", "RMC Sport", "Sport", "https://rmcsport.bfmtv.com/rss/fil-sport/"),
              ("ftvsport", "franceinfo sport", "Sport", "https://www.francetvinfo.fr/sports.rss")]


def _sentence(m: dict) -> str:
    if m["sport"] == "f1":
        return f"{m['gp']} ({m['session']}) : " + (", ".join(m.get("podium") or []) or "terminé")
    h, a = m["home"], m["away"]
    if m["sport"] == "tennis":
        hs_, as_s = (h.get("score") or "").split(), (a.get("score") or "").split()
        sets = list(zip(hs_, as_s))
        won = sum(int(x) > int(y) for x, y in sets if x.isdigit() and y.isdigit())
        w, l = (h, a) if won * 2 > len(sets) else (a, h)
        score = " ".join(f"{x}-{y}" if w is h else f"{y}-{x}" for x, y in sets)
        return f"{w['full']} bat {l['full']} {score}".strip()
    try:
        hs, as_ = float(h["score"]), float(a["score"])
    except (TypeError, ValueError):
        return f"{h['full']} – {a['full']}"
    if hs == as_:
        return f"{h['full']} et {a['full']} font match nul ({h['score']}-{a['score']})"
    w, l, ws, ls = (h, a, h["score"], a["score"]) if hs > as_ else (a, h, a["score"], h["score"])
    return f"{w['full']} bat {l['full']} {ws}-{ls}"


@router.get("/api/sportrecap")
async def sport_recap():
    """The day in sport: the big results in one sentence each, the highlights videos, the sport headlines."""
    from . import news
    sc, rp, guide, feeds = await asyncio.gather(scores(), replays(""), tv_guide(), asyncio.gather(*(news._fetch(*f) for f in SPORT_NEWS)))
    done = sorted((m for m in sc if m["state"] == "post"), key=lambda m: -m["score"])
    top = [{**m, "text": _sentence(m)} for m in done if not YOUTH.search(m["league"] + m.get("home", {}).get("full", ""))][:24]
    by_sport: dict[str, list] = {}
    for m in top:
        by_sport.setdefault("amical" if m["league"] == "Match amical" else m["sport"], []).append(m)
    arts = sorted((i for l in feeds for i in l), key=lambda i: i["ts"], reverse=True)
    news.remember(arts)
    tonight = [g for g in guide if not g["live"] and g["start"] < (_now() + timedelta(hours=14)).isoformat()][:12]
    return {"date": _now().isoformat(), "results": by_sport, "headline": top[0]["text"] if top else "",
            "videos": [v for v in rp if v["embed"]][:12], "articles": arts[:30], "tonight": tonight, "sports": SPORTS}


# ----------------------------------------------------------------- what's on the big channels right now
BIG_CHANNELS = re.compile(r"^(tf1|france [2345]|m6|arte|tmc|w9|tfx|c8|cstar|rmc story|rmc d[eé]couverte|l['’]?[eé]quipe|la cha[iî]ne l['’]?[eé]quipe|"
                          r"canal\+|gulli|france 4|6ter|cherie 25|nrj 12|tf1 s[eé]ries[- ]films)$", re.I)
KIND_SCORE = [(r"sport|football|rugby|tennis|basket|cyclisme|formule|handball", 5, "Sport"),
              (r"s[eé]rie", 3, "Série"), (r"divertissement|jeu|t[eé]l[eé]-?r[eé]alit[eé]|humour|spectacle|concert", 3, "Divertissement"),
              (r"documentaire|d[eé]couverte|histoire|nature|science", 3, "Documentaire"), (r"film|t[eé]l[eé]film|cin[eé]ma", 2, "Film"),
              (r"magazine", 2, "Magazine"), (r"journal|information|actualit", 1, "Info"), (r"jeunesse|dessin|animation", 1, "Jeunesse")]
SKIP_KIND = re.compile(r"m[eé]t[eé]o|t[eé]l[eé]-?achat|pas de diffusion|programme de nuit|fin des programmes|loterie|tirage", re.I)
_onair: dict = {"t": 0.0, "items": []}


def _parse_onair(raw: bytes) -> list[dict]:
    import gzip
    import unicodedata
    import xml.etree.ElementTree as ET
    root = ET.fromstring(gzip.decompress(raw))
    names = {c.get("id"): (c.findtext("display-name") or "") for c in root.findall("channel")}
    norm = lambda t: unicodedata.normalize("NFKD", t.replace("’", "'")).encode("ascii", "ignore").decode().lower().replace("la chaine ", "").strip()   # noqa: E731
    from . import tv
    hub = {}
    for c in tv.channels():
        if c["group"].startswith("TNT") or c["group"] == "Sport":
            hub.setdefault(norm(c["name"]), c["id"])
    now, out = _now(), []
    for p in root.findall("programme"):
        name = names.get(p.get("channel"), "")
        if not BIG_CHANNELS.match(name):
            continue
        try:
            start = datetime.strptime(p.get("start", ""), "%Y%m%d%H%M%S %z")
            stop = datetime.strptime(p.get("stop", ""), "%Y%m%d%H%M%S %z")
        except ValueError:
            continue
        if stop < now or start > now + timedelta(hours=4):
            continue
        cats = " ".join(c.text or "" for c in p.findall("category"))
        title = p.findtext("title") or ""
        if SKIP_KIND.search(f"{cats} {title}"):
            continue
        score, kind = next(((sc, k) for r, sc, k in KIND_SCORE if re.search(r, cats, re.I)), (1, cats.split(" ")[0] if cats else ""))
        icon = p.find("icon")
        hub_id = hub.get(norm(name))
        out.append({"channel": name, "title": title, "sub": p.findtext("sub-title") or "", "desc": (p.findtext("desc") or "")[:240],
                    "kind": kind, "score": score + (1 if (stop - start) >= timedelta(minutes=50) else 0),
                    "start": start.astimezone(timezone.utc).isoformat(), "stop": stop.astimezone(timezone.utc).isoformat(),
                    "img": icon.get("src", "") if icon is not None else "", "tv_id": hub_id, "free": hub_id is not None,
                    "web": "" if hub_id else _web(name)})
    return out


@router.get("/api/tv/onair")
async def on_air():
    """The most interesting thing on each big channel right now (sport > series/shows/docs > films > news), and what's next."""
    await tv_guide()   # keeps the guide file fresh
    from .main import DATA_DIR
    f = DATA_DIR / "epg_fr.xml.gz"
    if f.exists() and time.time() - _onair["t"] > 600:
        try:
            _onair.update(t=time.time(), items=await asyncio.to_thread(_parse_onair, f.read_bytes()))
        except Exception:  # noqa: BLE001
            pass
    now = _now().isoformat()
    items = [i for i in _onair["items"] if i["stop"] > now]
    current = sorted((i for i in items if i["start"] <= now), key=lambda i: (-i["score"], not i["free"]))
    seen, best = set(), []
    for i in current:
        if i["channel"] not in seen:
            seen.add(i["channel"])
            best.append(i)
    later = sorted((i for i in items if i["start"] > now and i["score"] >= 3), key=lambda i: (i["start"], -i["score"]))[:16]
    return {"now": best, "next": later}


KEY_FR = {"Goal": "But", "Goal - Header": "But de la tête", "Penalty - Scored": "Penalty marqué", "Own Goal": "But contre son camp",
          "Yellow Card": "Carton jaune", "Red Card": "Carton rouge", "Penalty - Missed": "Penalty manqué", "Halftime": "Mi-temps",
          "Try": "Essai", "Conversion": "Transformation", "Penalty Goal": "Pénalité", "Drop Goal": "Drop"}
FR_NAMES = {"France": "France", "Italy": "Italie", "Spain": "Espagne", "England": "Angleterre", "Germany": "Allemagne",
            "Netherlands": "Pays-Bas", "Belgium": "Belgique", "Portugal": "Portugal", "Croatia": "Croatie", "Switzerland": "Suisse",
            "Paris Saint-Germain": "PSG", "Marseille": "OM", "Lyon": "OL", "Bayern Munich": "Bayern", "Internazionale": "Inter"}


@router.get("/api/sportrecap/match")
async def match_summary(path: str, id: str):
    """The full story of one match: score, scorers/key moments (in French), photos, highlight videos,
    the match report with its key sentences in bold, and the French articles about it."""
    if not any(path == p for p, *_ in LEAGUES) or not id.isdigit():
        from fastapi import HTTPException
        raise HTTPException(404, "unknown match")
    from . import news
    try:
        r = await youtube.http.get(ESPN.replace("scoreboard", "summary").format(path), params={"event": id})
        d = r.json()
    except Exception:  # noqa: BLE001
        d = {}
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    teams = [{"name": t.get("team", {}).get("displayName", ""), "logo": (t.get("team", {}).get("logos") or [{}])[0].get("href", "") or t.get("team", {}).get("logo", ""),
              "score": t.get("score", ""), "home": t.get("homeAway") == "home", "winner": t.get("winner", False)} for t in comp.get("competitors", [])]
    teams.sort(key=lambda t: not t["home"])
    key = []
    for k in d.get("keyEvents") or d.get("scoringPlays") or []:
        kind = (k.get("type") or {}).get("text", "")
        if kind in KEY_FR or k.get("scoringPlay"):
            who = ", ".join(p.get("athlete", {}).get("displayName", "") for p in k.get("participants", [])[:1])
            key.append({"t": (k.get("clock") or {}).get("displayValue", ""), "kind": KEY_FR.get(kind, kind), "who": who,
                        "team": (k.get("team") or {}).get("displayName", ""), "text": k.get("text", "")})
    art = d.get("article") or {}
    blocks = []
    for para in re.split(r"</p>|<br\s*/?>|\n\s*\n|\n", art.get("story", "")):
        txt = re.sub(r"<[^>]+>", " ", para)
        import html as _h
        txt = " ".join(_h.unescape(txt).split())
        if len(txt) > 40:
            blocks.append({"t": "p", "x": txt})
    if blocks:
        news._highlight(blocks, art.get("headline", ""))
    photos = [i.get("url") for i in art.get("images", []) if i.get("url")][:4]
    videos = []
    for v in (d.get("videos") or [])[:6]:
        src = ((v.get("links") or {}).get("source") or {})
        url = (src.get("HD") or {}).get("href") or src.get("href")
        if url:
            videos.append({"title": v.get("headline", ""), "src": url, "thumb": v.get("thumbnail", "")})
    # French articles about the match (L'Équipe, RMC Sport, franceinfo) -> opened in the hub's reader
    feeds = await asyncio.gather(*(news._fetch(*f) for f in SPORT_NEWS))
    arts = [a for l in feeds for a in l]
    names = [FR_NAMES.get(t["name"], t["name"]) for t in teams]
    words = [w for n in names for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", n)]
    fr = [a for a in arts if sum(bool(re.search(rf"\b{re.escape(w)}\b", a["title"] + " " + a["summary"], re.I)) for w in words) >= min(2, len(words))]
    news.remember(fr)
    # a YouTube highlights video from the official channels, when there is one
    yt = []
    try:
        for v in await replays(""):
            if v.get("embed") and sum(w.lower() in v["title"].lower() for w in words) >= min(2, len(words)):
                yt.append(v)
    except Exception:  # noqa: BLE001
        pass
    return {"league": next((n for p, _, n, _ in LEAGUES if p == path), ""), "teams": teams,
            "status": ((comp.get("status") or {}).get("type") or {}).get("detail", ""), "venue": ((d.get("gameInfo") or {}).get("venue") or {}).get("fullName", ""),
            "headline": art.get("headline", ""), "description": art.get("description", ""), "blocks": blocks,
            "photos": photos, "videos": videos, "key": key[:30], "fr_articles": fr[:6], "yt": yt[:3]}


FR_NAMES.update({"Croatia": "Croatie", "Czechia": "Tchéquie", "Türkiye": "Turquie", "Turkey": "Turquie", "Greece": "Grèce",
                 "Serbia": "Serbie", "Norway": "Norvège", "Denmark": "Danemark", "Wales": "Pays de Galles", "Scotland": "Écosse",
                 "Ireland": "Irlande", "Northern Ireland": "Irlande du Nord", "South Africa": "Afrique du Sud", "New Zealand": "Nouvelle-Zélande",
                 "Australia": "Australie", "Argentina": "Argentine", "Brazil": "Brésil", "Japan": "Japon", "Hungary": "Hongrie",
                 "Poland": "Pologne", "Austria": "Autriche", "Sweden": "Suède", "Romania": "Roumanie", "Georgia": "Géorgie",
                 "Morocco": "Maroc", "Algeria": "Algérie", "Senegal": "Sénégal", "Tunisia": "Tunisie", "United States": "États-Unis",
                 "Slovakia": "Slovaquie", "Slovenia": "Slovénie", "Ukraine": "Ukraine", "Iceland": "Islande", "Finland": "Finlande",
                 "Albania": "Albanie", "Kosovo": "Kosovo", "Montenegro": "Monténégro", "Cyprus": "Chypre", "Armenia": "Arménie",
                 "Fiji": "Fidji", "Samoa": "Samoa", "Tonga": "Tonga", "Italy": "Italie", "Spain": "Espagne", "England": "Angleterre",
                 "Germany": "Allemagne", "Netherlands": "Pays-Bas", "Belgium": "Belgique", "Switzerland": "Suisse"})


def _plain(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", t.replace("’", "'")).encode("ascii", "ignore").decode().lower()


def _where(m: dict, guide: list[dict]) -> dict:
    """Which French channel shows this match (from the TV guide): both team names in the programme, within 2 h."""
    if m["sport"] == "f1" or not m.get("home"):
        return m
    try:
        when = datetime.fromisoformat(m["date"].replace("Z", "+00:00"))
    except ValueError:
        return m
    keys = []
    for t in (m["home"], m["away"]):
        fr = FR_NAMES.get(t.get("full", ""), t.get("full", ""))
        w = max(re.findall(r"[a-z]{4,}", _plain(fr)) or [""], key=len)
        keys.append(w)
    if not all(keys):
        return m
    for g in guide:
        try:
            gs = datetime.fromisoformat(g["start"])
        except ValueError:
            continue
        if abs((gs - when).total_seconds()) > 7200:
            continue
        text = _plain(f"{g['title']} {g['sub']}")
        if all(k in text for k in keys):
            return {**m, "tv": {"channel": g["channel"], "free": g["free"], "tv_id": g["tv_id"], "web": g.get("web", ""), "tnt": g.get("tnt", False)}}
    return m
