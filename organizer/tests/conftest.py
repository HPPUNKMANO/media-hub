import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Config  # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    # Make sure tests never call real services or ffprobe.
    monkeypatch.setattr("app.metadata.shutil.which", lambda _name: None)
    c = Config(media_root=tmp_path / "Media", state_dir=tmp_path / "state", stable_seconds=60, fetch_cover_art=False)
    c.ensure_dirs()
    return c


@pytest.fixture
def make_file(cfg):
    def _make(rel: str, content: bytes = b"x" * 2048, age: int = 3600) -> Path:
        p = cfg.inbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        t = time.time() - age
        os.utime(p, (t, t))
        return p
    return _make
