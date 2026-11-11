"""Filesystem operations. SAFETY CONTRACT: this module only ever *renames/moves*.

There is intentionally no code path that deletes, truncates or overwrites a file:
  * destinations that already exist get a " (2)", " (3)" ... suffix,
  * cross-device moves (which would need copy + delete) are refused,
  * every move is appended to an undo journal before returning.
tests/test_safety.py scans the source tree to make sure this stays true.
"""
from __future__ import annotations

import errno
import json
import os
import re
import threading
import time
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_journal_lock = threading.Lock()


def clean_name(text: str, max_len: int = 150) -> str:
    """Make a string safe as a single Windows/Linux path component."""
    text = _INVALID.sub(" ", str(text))
    text = re.sub(r"\s+", " ", text).strip().rstrip(". ")
    if text.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?i)(COM|LPT)\d", text):
        text = f"_{text}"
    return text[:max_len].rstrip(". ") or "Unknown"


def unique_path(dest: Path) -> Path:
    """Return dest, or dest with ' (n)' before the extension if it already exists."""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    n = 2
    while True:
        candidate = dest.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


class MoveError(Exception):
    pass


class Mover:
    """Moves files (or pretends to, in dry-run mode) and journals every move."""

    def __init__(self, journal: Path, run_id: str, dry_run: bool):
        self.journal = journal
        self.run_id = run_id
        self.dry_run = dry_run
        self.planned: set[Path] = set()  # destinations reserved during a dry run

    def _reserve(self, dest: Path) -> Path:
        dest = unique_path(dest)
        if self.dry_run:
            stem, suffix, n = dest.stem, dest.suffix, 2
            base = dest
            while dest in self.planned:
                dest = base.with_name(f"{stem} ({n}){suffix}")
                n += 1
            self.planned.add(dest)
        return dest

    def move(self, src: Path, dest: Path, reason: str = "") -> Path:
        if not src.exists():
            raise MoveError(f"source vanished: {src}")
        final = self._reserve(dest)
        if self.dry_run:
            return final
        final.parent.mkdir(parents=True, exist_ok=True)
        try:
            # os.rename never overwrites on Windows; on Linux we already
            # guaranteed `final` does not exist via unique_path().
            if final.exists():
                raise MoveError(f"destination appeared during move: {final}")
            os.rename(src, final)
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise MoveError("source and destination are on different drives; refusing copy+delete") from exc
            raise MoveError(str(exc)) from exc
        self._log(src, final, reason)
        return final

    def _log(self, src: Path, dest: Path, reason: str) -> None:
        rec = {"run_id": self.run_id, "ts": time.time(), "src": str(src), "dst": str(dest), "reason": reason}
        with _journal_lock:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            with self.journal.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
