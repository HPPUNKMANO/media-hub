"""Ask Jellyfin, Navidrome and Audiobookshelf to rescan after files were moved."""
from __future__ import annotations

import hashlib
import logging
import secrets

import requests

from .config import Config

log = logging.getLogger("organizer.refresh")


def refresh_all(cfg: Config, kinds: set[str]) -> dict:
    results = {}
    video = {"movie", "episode", "documentary", "education", "personal"}
    if kinds & video or "music" in kinds:
        results["jellyfin"] = _jellyfin(cfg)
    if "music" in kinds:
        results["navidrome"] = _navidrome(cfg)
    if kinds & {"podcast", "audiobook"}:
        results["audiobookshelf"] = _abs(cfg)
    return results


def _jellyfin(cfg: Config) -> str:
    if not cfg.jellyfin_key:
        return "skipped (JELLYFIN_API_KEY not set)"
    try:
        r = requests.post(f"{cfg.jellyfin_url}/Library/Refresh",
                          headers={"Authorization": f'MediaBrowser Token="{cfg.jellyfin_key}"'}, timeout=15)
        return "ok" if r.status_code < 300 else f"HTTP {r.status_code}"
    except requests.RequestException as exc:
        return f"error: {exc.__class__.__name__}"


def _navidrome(cfg: Config) -> str:
    if not (cfg.navidrome_user and cfg.navidrome_password):
        return "skipped (Navidrome credentials not set)"
    salt = secrets.token_hex(6)
    token = hashlib.md5((cfg.navidrome_password + salt).encode()).hexdigest()
    try:
        r = requests.get(f"{cfg.navidrome_url}/rest/startScan", timeout=15, params={
            "u": cfg.navidrome_user, "t": token, "s": salt, "v": "1.16.1", "c": "media-hub", "f": "json"})
        ok = r.ok and r.json().get("subsonic-response", {}).get("status") == "ok"
        return "ok" if ok else f"failed (HTTP {r.status_code})"
    except (requests.RequestException, ValueError) as exc:
        return f"error: {exc.__class__.__name__}"


def _abs(cfg: Config) -> str:
    if not cfg.abs_token:
        return "skipped (ABS_API_TOKEN not set)"
    h = {"Authorization": f"Bearer {cfg.abs_token}"}
    try:
        libs = requests.get(f"{cfg.abs_url}/api/libraries", headers=h, timeout=15).json().get("libraries", [])
        for lib in libs:
            requests.post(f"{cfg.abs_url}/api/libraries/{lib['id']}/scan", headers=h, timeout=15)
        return f"ok ({len(libs)} libraries)"
    except (requests.RequestException, ValueError) as exc:
        return f"error: {exc.__class__.__name__}"
