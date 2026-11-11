"""Build target paths following the Jellyfin / Navidrome naming conventions."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .fsops import clean_name

_LANG_RE = re.compile(r"\.(?P<lang>[a-z]{2,3}(-[A-Za-z]{2})?)(?P<flags>(\.(forced|sdh|cc|default|hi))*)$", re.IGNORECASE)


def title_year(title: str, year: int | None) -> str:
    title = clean_name(title)
    return f"{title} ({year})" if year else title


def movie_path(root: Path, title: str, year: int | None, ext: str) -> Path:
    base = title_year(title, year)
    return root / base / f"{base}{ext.lower()}"


def episode_path(root: Path, show: str, show_year: int | None, season: int, episode: int,
                 episode_title: str, ext: str) -> Path:
    show_dir = title_year(show, show_year)
    name = f"{clean_name(show)} - S{season:02d}E{episode:02d}"
    if episode_title:
        name += f" - {clean_name(episode_title)}"
    return root / show_dir / f"Season {season:02d}" / f"{name}{ext.lower()}"


def personal_path(root: Path, src: Path, when: datetime) -> Path:
    return root / f"{when:%Y}" / f"{when:%Y-%m}" / clean_name(src.name)


def music_path(root: Path, tags: dict, ext: str) -> Path:
    artist = clean_name(tags.get("albumartist") or tags.get("artist") or "Unknown Artist")
    album = tags.get("album") or ""
    year = tags.get("year")
    title = clean_name(tags.get("title") or "Unknown Title")
    track = tags.get("track")
    disc = tags.get("disc")
    disc_total = tags.get("disctotal")
    if album:
        album_dir = clean_name(f"{album} ({year})" if year else album)
    else:
        album_dir = "Singles"
    prefix = ""
    if track:
        prefix = f"{track:02d} - "
        if disc and (disc_total or 0) > 1:
            prefix = f"{disc}-{track:02d} - "
    return root / artist / album_dir / f"{prefix}{title}{ext.lower()}"


def podcast_path(root: Path, tags: dict, src: Path) -> Path:
    show = clean_name(tags.get("album") or tags.get("artist") or src.parent.name or "Unsorted")
    return root / show / clean_name(src.name)


def audiobook_path(root: Path, tags: dict, src: Path) -> Path:
    author = clean_name(tags.get("albumartist") or tags.get("artist") or "Unknown Author")
    book = clean_name(tags.get("album") or src.stem)
    return root / author / book / clean_name(src.name)


def subtitle_suffix(sub: Path, video_stem: str) -> str:
    """Keep language/forced flags of a sidecar subtitle: 'Movie.en.forced.srt' -> '.en.forced.srt'."""
    stem = sub.stem
    rest = stem[len(video_stem):] if stem.lower().startswith(video_stem.lower()) else ""
    m = _LANG_RE.search(stem)
    if rest and rest.startswith("."):
        return f"{rest}{sub.suffix.lower()}"
    if m:
        return f".{m['lang'].lower()}{m['flags'].lower()}{sub.suffix.lower()}"
    return sub.suffix.lower()
