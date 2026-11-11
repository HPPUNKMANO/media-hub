"""One organizer pass over C:\\Media\\_Inbox. Never deletes anything (see fsops.py)."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from . import naming
from .classify import Guess, classify
from .config import AUDIO_EXT, IGNORED_NAMES, PARTIAL_EXT, SUBTITLE_EXT, VIDEO_EXT, Config
from .dedupe import DuplicateFinder, HashCache
from .fsops import Mover, MoveError
from .metadata import TMDb, fetch_cover_art, probe, read_tags, tags_from_filename
from .refresh import refresh_all

log = logging.getLogger("organizer.engine")
RUN_LOCK = threading.Lock()
MIN_TMDB_SCORE = 0.75
ORPHAN_SUBTITLE_DAYS = 7


class Review(Exception):
    """Raised by a handler when a file should go to _Review instead."""


class Duplicate(Exception):
    """Raised by a handler when the library already holds another version of the item."""


_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_EP_RE = re.compile(r"(?i)s\d{1,2}e\d{1,3}|\d{1,2}x\d{2}")
_JUNK_RE = re.compile(r"(?i)^(copy|copie|new|untitled|video|movie|film|download|sans titre)\b|\bcopy\b|\(\d\)$")


def _name_quality(p: Path) -> int:
    stem = p.stem
    score = 0
    if _YEAR_RE.search(stem):
        score += 2
    if _EP_RE.search(stem):
        score += 2
    if " - " in stem:
        score += 1
    if _JUNK_RE.search(stem):
        score -= 3
    return score


def _items_with_prefix(folder: Path, prefix: str, exts: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    return [p for p in folder.iterdir() if p.suffix.lower() in exts and p.stem.lower().startswith(prefix.lower())]


class Organizer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.tmdb = TMDb(cfg.tmdb_key, cfg.language)
        self.cache = HashCache(cfg.state_dir / "hashes.db")

    # ------------------------------------------------------------------ public
    def run(self, dry_run: bool = True) -> dict:
        if not RUN_LOCK.acquire(blocking=False):
            return {"status": "busy", "message": "an organizer run is already in progress"}
        try:
            return self._run(dry_run)
        finally:
            RUN_LOCK.release()

    # ----------------------------------------------------------------- private
    def _run(self, dry_run: bool) -> dict:
        cfg = self.cfg
        cfg.ensure_dirs()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        started = time.time()
        self.mover = Mover(cfg.state_dir / "moves.jsonl", run_id, dry_run)
        self.dry_run = dry_run
        self.finder = DuplicateFinder(cfg.media_root, self.cache)
        self.items: list[dict] = []
        self.kinds_moved: set[str] = set()
        self.album_dirs: dict[Path, dict] = {}
        self.queue_notes: dict[str, str] = {}

        files, subs = self._scan()
        # Videos first so their subtitles travel with them; within a group, the most descriptive
        # names first, so that in an identical pair the well-named copy is filed and the other is flagged.
        files.sort(key=lambda p: (p.suffix.lower() not in VIDEO_EXT, -_name_quality(p), str(p).lower()))
        for src in files:
            self._process(src, subs)

        for sub in subs:
            if sub.exists() and time.time() - sub.stat().st_mtime > ORPHAN_SUBTITLE_DAYS * 86400:
                self._to_review(sub, "subtitle without a matching video for 7+ days", "subtitle")

        if not dry_run and cfg.fetch_cover_art:
            for album_dir, tags in self.album_dirs.items():
                fetch_cover_art(album_dir, tags.get("albumartist") or tags.get("artist", ""), tags.get("album", ""),
                                tags.get("mb_albumid", ""))

        refresh = {} if dry_run or not self.kinds_moved else refresh_all(cfg, self.kinds_moved)
        counts: dict[str, int] = {}
        for it in self.items:
            counts[it["action"]] = counts.get(it["action"], 0) + 1
        report = {
            "run_id": run_id,
            "dry_run": dry_run,
            "started": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
            "duration_s": round(time.time() - started, 1),
            "tmdb": "enabled" if self.tmdb.enabled else "disabled (no TMDB_API_KEY: names come from file names only)",
            "counts": counts,
            "items": self.items,
            "refresh": refresh,
        }
        self._save_report(report)
        return report

    def _scan(self) -> tuple[list[Path], list[Path]]:
        files, subs = [], []
        now = time.time()
        for dirpath, dirnames, filenames in os.walk(self.cfg.inbox):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                low = name.lower()
                if low in IGNORED_NAMES or name.startswith(".") or p.suffix.lower() in PARTIAL_EXT:
                    continue
                if any((p.parent / (name + ext)).exists() for ext in PARTIAL_EXT):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if now - st.st_mtime < self.cfg.stable_seconds:
                    self.items.append({"action": "waiting", "src": self._rel(p), "reason": "file was modified recently (still copying?)"})
                    continue
                (subs if p.suffix.lower() in SUBTITLE_EXT else files).append(p)
        return files, subs

    def _rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.cfg.media_root)).replace("\\", "/")
        except ValueError:
            return str(p)

    def _record(self, action: str, src: Path, dst: Path | None, kind: str, reason: str = "") -> None:
        self.items.append({"action": action, "kind": kind, "src": self._rel(src),
                           "dst": self._rel(dst) if dst else None, "reason": reason})

    def _process(self, src: Path, subs: list[Path]) -> None:
        if not src.exists():
            return
        guess = Guess(kind="unknown")
        try:
            dup = self.finder.find(src)
            if dup is not None:
                self._to_duplicates(src, f"identical to {self._rel(dup)}", "duplicate")
                return
            guess = classify(src, self.cfg.inbox)
            handler = getattr(self, f"_h_{guess.kind}", None)
            if handler is None:
                raise Review(guess.extra.get("reason", "could not identify this file"))
            if src.suffix.lower() in VIDEO_EXT | AUDIO_EXT:
                ok, detail = probe(src)
                if not ok:
                    raise Review(f"file is unreadable or corrupt: {detail}")
            dest, reason = handler(src, guess)
            final = self.mover.move(src, dest, reason)
            self.finder.add(src if self.dry_run else final)
            self.kinds_moved.add(guess.kind)
            self._record("organized", src, final, guess.kind, reason)
            if src.suffix.lower() in VIDEO_EXT:
                self._move_subtitles(src, final, subs)
        except Duplicate as d:
            self._to_duplicates(src, str(d), guess.kind)
        except Review as r:
            self._to_review(src, str(r), guess.kind)
        except MoveError as e:
            self._record("error", src, None, guess.kind, str(e))
        except Exception as e:  # keep going on unexpected per-file errors
            log.exception("failed on %s", src)
            self._record("error", src, None, guess.kind, f"{e.__class__.__name__}: {e}")

    def _relative_inbox(self, src: Path) -> Path:
        try:
            return src.relative_to(self.cfg.inbox)
        except ValueError:
            return Path(src.name)

    def _to_review(self, src: Path, reason: str, kind: str) -> None:
        try:
            final = self.mover.move(src, self.cfg.review / self._relative_inbox(src), reason)
            self._record("review", src, final, kind, reason)
            self._note(final, reason)
        except MoveError as e:
            self._record("error", src, None, kind, str(e))

    def _to_duplicates(self, src: Path, reason: str, kind: str) -> None:
        try:
            final = self.mover.move(src, self.cfg.duplicates / self._relative_inbox(src), reason)
            self._record("duplicate", src, final, kind, reason)
            self._note(final, reason)
        except MoveError as e:
            self._record("error", src, None, kind, str(e))

    def _note(self, final: Path, reason: str) -> None:
        if self.dry_run:
            return
        notes_path = self.cfg.state_dir / "queue_notes.json"
        try:
            notes = json.loads(notes_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            notes = {}
        notes[self._rel(final)] = reason
        notes_path.write_text(json.dumps(notes, indent=1, ensure_ascii=False), encoding="utf-8")

    def _move_subtitles(self, video_src: Path, video_final: Path, subs: list[Path]) -> None:
        for sub in list(subs):
            if sub.parent == video_src.parent and sub.stem.lower().startswith(video_src.stem.lower()):
                suffix = naming.subtitle_suffix(sub, video_src.stem)
                dest = video_final.with_name(video_final.stem + suffix)
                try:
                    final = self.mover.move(sub, dest, "subtitle of " + video_final.name)
                    self._record("organized", sub, final, "subtitle", "moved with its video")
                    subs.remove(sub)
                except MoveError as e:
                    self._record("error", sub, None, "subtitle", str(e))

    # ------------------------------------------------------------ handlers
    def _check_existing_video(self, dest: Path, prefix: str) -> None:
        if _items_with_prefix(dest.parent, prefix, VIDEO_EXT):
            raise Duplicate(f"another version of '{prefix}' is already in the library ({self._rel(dest.parent)})")

    def _resolve_movie(self, guess: Guess, use_tmdb: bool) -> tuple[str, int | None, str]:
        if not guess.title:
            raise Review("could not read a title from the file name")
        if use_tmdb and self.tmdb.enabled:
            m = self.tmdb.movie(guess.title, guess.year)
            if not m or m[3] < MIN_TMDB_SCORE:
                raise Review(f"no confident TMDb match for '{guess.title}' ({guess.year or 'no year'})")
            return m[0], m[1], f"TMDb #{m[2]} (score {m[3]:.2f})"
        return guess.title, guess.year, "from file name"

    def _resolve_show(self, guess: Guess, use_tmdb: bool) -> tuple[str, int | None, str, str]:
        if not guess.title or guess.episode is None:
            raise Review("could not read show / season / episode from the file name")
        if use_tmdb and self.tmdb.enabled:
            s = self.tmdb.show(guess.title, guess.year)
            if not s or s[3] < MIN_TMDB_SCORE:
                raise Review(f"no confident TMDb match for show '{guess.title}'")
            ep_title = self.tmdb.episode_title(s[2], guess.season or 1, guess.episode) or guess.episode_title
            return s[0], s[1], ep_title, f"TMDb #{s[2]} (score {s[3]:.2f})"
        return guess.title, guess.year, guess.episode_title, "from file name"

    def _h_movie(self, src: Path, guess: Guess, root: str = "Movies", use_tmdb: bool = True):
        if root == "Movies" and not self.tmdb.enabled and not guess.year:
            raise Review("no year in the file name and TMDb is not configured: rename to 'Title (Year).ext' "
                         "or set TMDB_API_KEY")
        title, year, how = self._resolve_movie(guess, use_tmdb)
        dest = naming.movie_path(self.cfg.lib(root), title, year, src.suffix)
        self._check_existing_video(dest, naming.title_year(title, year))
        return dest, how

    def _h_episode(self, src: Path, guess: Guess, root: str = "TV", use_tmdb: bool = True):
        show, year, ep_title, how = self._resolve_show(guess, use_tmdb)
        season = guess.season or 1
        dest = naming.episode_path(self.cfg.lib(root), show, year, season, guess.episode, ep_title, src.suffix)
        self._check_existing_video(dest, f"{naming.clean_name(show)} - S{season:02d}E{guess.episode:02d}")
        return dest, how

    def _h_documentary(self, src: Path, guess: Guess):
        if guess.episode is not None:
            return self._h_episode(src, guess, root="Documentaries")
        try:
            return self._h_movie(src, guess, root="Documentaries")
        except Review:
            return self._h_movie(src, guess, root="Documentaries", use_tmdb=False)

    def _h_education(self, src: Path, guess: Guess):
        # Lectures and courses are rarely on TMDb: keep names from the files.
        if guess.episode is not None:
            return self._h_episode(src, guess, root="Education", use_tmdb=False)
        if not guess.title:
            guess.title = src.stem
        return self._h_movie(src, guess, root="Education", use_tmdb=False)

    def _h_personal(self, src: Path, guess: Guess):
        when = guess.date or datetime.fromtimestamp(src.stat().st_mtime)
        how = "date from file name" if guess.date else "date from file modification time"
        return naming.personal_path(self.cfg.lib("Personal"), src, when), how

    def _audio_tags(self, src: Path) -> dict:
        tags = read_tags(src)
        if not tags.get("title"):
            tags = {**tags, **{k: v for k, v in tags_from_filename(src).items() if not tags.get(k)}}
        return tags

    def _h_music(self, src: Path, guess: Guess):
        tags = self._audio_tags(src)
        if not tags.get("title") or not (tags.get("artist") or tags.get("albumartist")):
            raise Review("no artist/title tags and file name is not 'Artist - Title'")
        dest = naming.music_path(self.cfg.lib("Music"), tags, src.suffix)
        if dest.exists():
            raise Duplicate(f"a different file for this track already exists: {self._rel(dest)}")
        if tags.get("album"):
            self.album_dirs.setdefault(dest.parent, tags)
        return dest, "from embedded tags" if read_tags(src).get("title") else "from file name"

    def _h_podcast(self, src: Path, guess: Guess):
        return naming.podcast_path(self.cfg.lib("Podcasts"), self._audio_tags(src), src), "podcast"

    def _h_audiobook(self, src: Path, guess: Guess):
        return naming.audiobook_path(self.cfg.lib("Audiobooks"), self._audio_tags(src), src), "audiobook"

    # ----------------------------------------------------------- reports
    def _save_report(self, report: dict) -> None:
        reports = self.cfg.state_dir / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        data = json.dumps(report, indent=1, ensure_ascii=False)
        (reports / "last.json").write_text(data, encoding="utf-8")
        if report["items"]:
            (reports / f"{report['run_id']}{'-dry' if report['dry_run'] else ''}.json").write_text(data, encoding="utf-8")
