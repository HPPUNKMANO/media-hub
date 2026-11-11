"""Exact-duplicate detection: size index first, then a cheap partial hash, then full SHA-256.

Hashes are cached in SQLite keyed by (path, size, mtime) so a library is only hashed once.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path

CHUNK = 1024 * 1024  # 1 MiB
SKIP_DIRS = {"_Inbox", "_Review", "_Duplicates", ".trash", "@eaDir", "metadata"}


class HashCache:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS hashes (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, quick TEXT, full TEXT)"
        )
        self._db.commit()

    def _row(self, p: Path, st: os.stat_result):
        with self._lock:
            row = self._db.execute("SELECT size, mtime, quick, full FROM hashes WHERE path=?", (str(p),)).fetchone()
        if row and row[0] == st.st_size and abs(row[1] - st.st_mtime) < 1e-3:
            return row
        return None

    def _store(self, p: Path, st: os.stat_result, quick: str | None, full: str | None):
        with self._lock:
            self._db.execute(
                "INSERT INTO hashes(path,size,mtime,quick,full) VALUES(?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime, "
                "quick=COALESCE(excluded.quick, hashes.quick), full=COALESCE(excluded.full, hashes.full)",
                (str(p), st.st_size, st.st_mtime, quick, full),
            )
            self._db.commit()

    def quick(self, p: Path) -> str:
        st = p.stat()
        row = self._row(p, st)
        if row and row[2]:
            return row[2]
        h = hashlib.sha256(str(st.st_size).encode())
        with p.open("rb") as fh:
            h.update(fh.read(CHUNK))
            if st.st_size > 2 * CHUNK:
                fh.seek(-CHUNK, os.SEEK_END)
                h.update(fh.read(CHUNK))
        value = h.hexdigest()
        self._store(p, st, value, None)
        return value

    def full(self, p: Path) -> str:
        st = p.stat()
        row = self._row(p, st)
        if row and row[3]:
            return row[3]
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(lambda: fh.read(CHUNK * 4), b""):
                h.update(block)
        value = h.hexdigest()
        self._store(p, st, None, value)
        return value


class DuplicateFinder:
    """Index of every file already in the library, by size."""

    def __init__(self, media_root: Path, cache: HashCache):
        self.cache = cache
        self.by_size: dict[int, list[Path]] = defaultdict(list)
        for dirpath, dirnames, filenames in os.walk(media_root):
            if Path(dirpath) == media_root:
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                p = Path(dirpath) / f
                try:
                    self.by_size[p.stat().st_size].append(p)
                except OSError:
                    continue

    def find(self, candidate: Path) -> Path | None:
        """Return an existing library file with identical content, if any."""
        size = candidate.stat().st_size
        if size == 0:
            return None
        others = [o for o in self.by_size.get(size, []) if o != candidate and o.exists()]
        if not others:
            return None
        q = self.cache.quick(candidate)
        for other in others:
            if self.cache.quick(other) == q and self.cache.full(other) == self.cache.full(candidate):
                return other
        return None

    def add(self, path: Path) -> None:
        """Register a file that was just placed in the library (also catches dupes inside one inbox batch)."""
        try:
            self.by_size[path.stat().st_size].append(path)
        except OSError:
            pass
