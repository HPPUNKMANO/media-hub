"""Runtime configuration for the organizer, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".webm", ".mpg", ".mpeg", ".ts", ".m2ts", ".flv", ".ogv", ".3gp"}
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".alac", ".aiff", ".aif", ".ape", ".m4b"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".dng"}
SUBTITLE_EXT = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup"}
# Files that are still being downloaded / written: never touch them.
PARTIAL_EXT = {".part", ".crdownload", ".tmp", ".!qb", ".partial", ".download", ".opdownload"}
IGNORED_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", "readme.txt"}

# Sub-folders of _Inbox that act as "hints" for what the content is.
HINT_FOLDERS = {
    "movies": "movie",
    "tv": "episode",
    "documentaries": "documentary",
    "education": "education",
    "personal": "personal",
    "music": "music",
    "podcasts": "podcast",
    "audiobooks": "audiobook",
}


@dataclass
class Config:
    media_root: Path
    state_dir: Path
    tmdb_key: str = ""
    language: str = "en-US"
    stable_seconds: int = 120
    fetch_cover_art: bool = True
    jellyfin_url: str = ""
    jellyfin_key: str = ""
    navidrome_url: str = ""
    navidrome_user: str = ""
    navidrome_password: str = ""
    abs_url: str = ""
    abs_token: str = ""
    library_dirs: dict = field(default_factory=dict)

    @property
    def inbox(self) -> Path:
        return self.media_root / "_Inbox"

    @property
    def review(self) -> Path:
        return self.media_root / "_Review"

    @property
    def duplicates(self) -> Path:
        return self.media_root / "_Duplicates"

    def lib(self, name: str) -> Path:
        return self.media_root / self.library_dirs.get(name, name)

    def ensure_dirs(self) -> None:
        for p in [self.inbox, self.review, self.duplicates, self.state_dir, self.state_dir / "reports"]:
            p.mkdir(parents=True, exist_ok=True)
        for name in ["Movies", "TV", "Documentaries", "Education", "Personal", "Music", "Podcasts", "Audiobooks"]:
            self.lib(name).mkdir(parents=True, exist_ok=True)
        for hint in ["Movies", "TV", "Documentaries", "Education", "Personal", "Music", "Podcasts", "Audiobooks"]:
            (self.inbox / hint).mkdir(parents=True, exist_ok=True)


def from_env() -> Config:
    e = os.environ.get
    return Config(
        media_root=Path(e("MEDIA_DIR", "/media")),
        state_dir=Path(e("STATE_DIR", "/state")),
        tmdb_key=e("TMDB_API_KEY", "").strip(),
        language=e("METADATA_LANGUAGE", "en-US"),
        stable_seconds=int(e("ORGANIZER_STABLE_SECONDS", "120")),
        fetch_cover_art=e("ORGANIZER_FETCH_COVER_ART", "true").lower() == "true",
        jellyfin_url=e("JELLYFIN_URL", "http://jellyfin:8096"),
        jellyfin_key=e("JELLYFIN_API_KEY", "").strip(),
        navidrome_url=e("NAVIDROME_URL", "http://navidrome:4533"),
        navidrome_user=e("NAVIDROME_USER", "").strip(),
        navidrome_password=e("NAVIDROME_PASSWORD", "").strip(),
        abs_url=e("ABS_URL", "http://audiobookshelf:80"),
        abs_token=e("ABS_API_TOKEN", "").strip(),
    )
