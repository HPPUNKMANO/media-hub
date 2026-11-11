"""Metadata from authorized, free sources: TMDb (video), embedded tags (audio),
MusicBrainz + Cover Art Archive (album art). Everything degrades gracefully offline."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

log = logging.getLogger("organizer.metadata")
UA = {"User-Agent": "PersonalMediaHub-Organizer/1.0 (self-hosted, personal use)"}
TMDB = "https://api.themoviedb.org/3"


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class TMDb:
    def __init__(self, key: str, language: str = "en-US"):
        self.key = key
        self.language = language
        self.session = requests.Session()
        self.session.headers.update(UA)
        if len(key) > 40:  # v4 "read access token"
            self.session.headers["Authorization"] = f"Bearer {key}"
            self.params = {}
        else:
            self.params = {"api_key": key}
        self._cache: dict = {}

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _get(self, path: str, **params):
        ck = (path, tuple(sorted(params.items())))
        if ck in self._cache:
            return self._cache[ck]
        r = self.session.get(f"{TMDB}{path}", params={**self.params, "language": self.language, **params}, timeout=15)
        r.raise_for_status()
        data = r.json()
        self._cache[ck] = data
        return data

    def movie(self, title: str, year: int | None):
        """Return (title, year, tmdb_id, confidence) or None."""
        res = self._get("/search/movie", query=title, **({"year": year} if year else {})).get("results", [])
        if not res and year:
            res = self._get("/search/movie", query=title).get("results", [])
        return self._best(res, title, year, "title", "release_date", "original_title")

    def show(self, title: str, year: int | None):
        res = self._get("/search/tv", query=title, **({"first_air_date_year": year} if year else {})).get("results", [])
        if not res and year:
            res = self._get("/search/tv", query=title).get("results", [])
        return self._best(res, title, year, "name", "first_air_date", "original_name")

    def episode_title(self, show_id: int, season: int, episode: int) -> str:
        try:
            return self._get(f"/tv/{show_id}/season/{season}/episode/{episode}").get("name", "") or ""
        except requests.RequestException:
            return ""

    @staticmethod
    def _best(results, title, year, name_key, date_key, orig_key):
        best = None
        for r in results[:8]:
            name = r.get(name_key) or ""
            score = max(_similar(title, name), _similar(title, r.get(orig_key) or ""))
            ry = int(r[date_key][:4]) if r.get(date_key) else None
            if year and ry:
                score += 0.15 if abs(ry - year) <= 1 else -0.2
            score += min(r.get("popularity", 0), 100) / 2000  # tie-breaker
            if best is None or score > best[3]:
                best = (name, ry, r.get("id"), score)
        return best


def read_tags(path: Path) -> dict:
    """Read common audio tags with mutagen (easy interface)."""
    try:
        import mutagen
    except ImportError:  # pragma: no cover
        return {}
    try:
        f = mutagen.File(str(path), easy=True)
    except Exception:
        return {}
    if not f or not f.tags:
        return {}

    def first(key):
        v = f.tags.get(key)
        return str(v[0]).strip() if v else ""

    def num(key):
        raw = first(key)
        part = raw.split("/")
        try:
            n = int(part[0]) if part[0] else None
        except ValueError:
            n = None
        try:
            total = int(part[1]) if len(part) > 1 and part[1] else None
        except ValueError:
            total = None
        return n, total

    track, _ = num("tracknumber")
    disc, disctotal = num("discnumber")
    year = None
    date = first("date") or first("originaldate")
    if date[:4].isdigit():
        year = int(date[:4])
    return {
        "artist": first("artist"),
        "albumartist": first("albumartist"),
        "album": first("album"),
        "title": first("title"),
        "track": track,
        "disc": disc,
        "disctotal": disctotal,
        "year": year,
        "mb_albumid": first("musicbrainz_albumid"),
    }


def tags_from_filename(path: Path) -> dict:
    """'Artist - Title.mp3' → tags, as a fallback when files have no tags."""
    stem = path.stem
    parts = [p.strip() for p in stem.split(" - ")]
    if len(parts) >= 2 and parts[0] and parts[-1]:
        artist, title = parts[0], parts[-1]
        if artist.isdigit() and len(parts) >= 3:  # "01 - Artist - Title"
            artist = parts[1]
        return {"artist": artist, "title": title}
    return {}


_last_mb_call = 0.0


def fetch_cover_art(album_dir: Path, artist: str, album: str, mb_albumid: str = "") -> bool:
    """Download front cover from the Cover Art Archive into album_dir/cover.jpg (never overwrites)."""
    global _last_mb_call
    target = album_dir / "cover.jpg"
    if target.exists() or any((album_dir / n).exists() for n in ("folder.jpg", "cover.png", "folder.png")):
        return False
    try:
        if not mb_albumid:
            wait = 1.1 - (time.time() - _last_mb_call)
            if wait > 0:
                time.sleep(wait)  # MusicBrainz asks for max 1 request/second
            _last_mb_call = time.time()
            q = f'release:"{album}" AND artist:"{artist}"'
            r = requests.get("https://musicbrainz.org/ws/2/release/", params={"query": q, "fmt": "json", "limit": 5},
                             headers=UA, timeout=15)
            r.raise_for_status()
            releases = [x for x in r.json().get("releases", []) if x.get("score", 0) >= 90]
            if not releases:
                return False
            mb_albumid = releases[0]["id"]
        img = requests.get(f"https://coverartarchive.org/release/{mb_albumid}/front-500", headers=UA, timeout=20)
        if img.status_code != 200 or not img.content:
            return False
        if target.exists():
            return False
        with target.open("xb") as fh:  # 'x' = fail if exists, never overwrite
            fh.write(img.content)
        return True
    except (requests.RequestException, OSError, ValueError) as exc:
        log.info("cover art not fetched for %s / %s: %s", artist, album, exc)
        return False


def probe(path: Path) -> tuple[bool, str]:
    """Check a media file is readable with ffprobe. Returns (ok, detail). Skips if ffprobe is absent."""
    exe = shutil.which("ffprobe")
    if not exe:
        return True, "ffprobe not available"
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration,format_name", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "ffprobe timed out"
    if out.returncode != 0:
        return False, (out.stderr.strip() or "ffprobe failed")[:300]
    try:
        fmt = json.loads(out.stdout).get("format", {})
        return True, f"{fmt.get('format_name', '?')}, {float(fmt.get('duration', 0)) / 60:.0f} min"
    except (ValueError, TypeError):
        return True, "probed"
