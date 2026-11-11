"""Decide what a file in the inbox is, using folder hints, extensions, filename patterns and guessit."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import AUDIO_EXT, HINT_FOLDERS, IMAGE_EXT, SUBTITLE_EXT, VIDEO_EXT

try:
    from guessit import guessit
except ImportError:  # pragma: no cover - guessit is installed in the container
    guessit = None

# Camera / phone / screen-recorder file names → personal media.
_PERSONAL_PATTERNS = [
    r"^(IMG|VID|MVI|MOV|DSC|DSCF|DSCN|DJI|GOPR|GX\d\d|GH\d\d|PXL|SAM|WP|P\d{7}|PANO|Screen ?Recording|Screenshot|WhatsApp (Video|Image))[\s_-]?",
    r"^\d{8}[_-]\d{6}",           # 20240131_154501
    r"^\d{4}-\d{2}-\d{2}[ _-]\d{2}[.:-]?\d{2}",  # 2024-01-31 15.45
]
_PERSONAL_RE = re.compile("|".join(_PERSONAL_PATTERNS), re.IGNORECASE)
_DATE_RES = [
    re.compile(r"(?P<y>(19|20)\d{2})(?P<m>[01]\d)(?P<d>[0-3]\d)[_-]?\d{0,6}"),
    re.compile(r"(?P<y>(19|20)\d{2})-(?P<m>[01]\d)-(?P<d>[0-3]\d)"),
]


@dataclass
class Guess:
    kind: str                     # movie | episode | documentary | education | personal | music | podcast | audiobook | subtitle | unknown
    title: str = ""
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    episode_title: str = ""
    language: str = ""            # for subtitles
    date: datetime | None = None  # for personal media
    hint: str = ""                # folder hint, if any
    extra: dict = field(default_factory=dict)


def folder_hint(path: Path, inbox: Path) -> str:
    try:
        rel = path.relative_to(inbox)
    except ValueError:
        return ""
    if len(rel.parts) > 1:
        return HINT_FOLDERS.get(rel.parts[0].lower(), "")
    return ""


def personal_date(path: Path) -> datetime | None:
    for rx in _DATE_RES:
        m = rx.search(path.stem)
        if m:
            try:
                return datetime(int(m["y"]), int(m["m"]), int(m["d"]))
            except ValueError:
                continue
    return None


def looks_personal(path: Path) -> bool:
    return bool(_PERSONAL_RE.search(path.stem))


def _guessit(name: str) -> dict:
    if guessit is None:
        return {}
    try:
        return dict(guessit(name))
    except Exception:
        return {}


def _first_int(value) -> int | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return int(value) if isinstance(value, int) else None


def classify(path: Path, inbox: Path) -> Guess:
    ext = path.suffix.lower()
    hint = folder_hint(path, inbox)

    if ext in SUBTITLE_EXT:
        return Guess(kind="subtitle", hint=hint)

    if ext in AUDIO_EXT:
        if hint in {"podcast", "audiobook"}:
            return Guess(kind=hint, hint=hint)
        if ext == ".m4b":
            return Guess(kind="audiobook", hint=hint)
        return Guess(kind="music", hint=hint)

    if ext in IMAGE_EXT:
        if hint == "personal" or looks_personal(path):
            return Guess(kind="personal", date=personal_date(path), hint=hint)
        return Guess(kind="unknown", hint=hint, extra={"reason": "image that is not a camera/phone photo"})

    if ext not in VIDEO_EXT:
        return Guess(kind="unknown", hint=hint, extra={"reason": f"unsupported file type '{ext}'"})

    if hint == "personal" or (not hint and looks_personal(path)):
        return Guess(kind="personal", date=personal_date(path), hint=hint)

    # Use parent folder name too: "Show Name/Season 1/01.mkv" style releases.
    name = path.name
    if path.parent != inbox and path.parent.name.lower() not in HINT_FOLDERS:
        name = f"{path.parent.name}/{path.name}"
    g = _guessit(name)
    if not g.get("title") and path.parent != inbox:
        g = _guessit(path.name)

    title = str(g.get("title", "")).strip()
    year = _first_int(g.get("year"))
    gtype = g.get("type")
    season = _first_int(g.get("season"))
    episode = _first_int(g.get("episode"))
    if gtype == "episode" and episode is not None and season is None:
        season = 1

    if hint == "episode" or (gtype == "episode" and episode is not None and hint not in {"movie"}):
        kind = "episode"
    else:
        kind = "movie"
    if hint in {"documentary", "education"}:
        kind = hint  # layout handled by naming: series-style if season/episode present

    return Guess(
        kind=kind,
        title=title,
        year=year,
        season=season,
        episode=episode,
        episode_title=str(g.get("episode_title", "") or ""),
        hint=hint,
        extra={"guessit_type": gtype},
    )
