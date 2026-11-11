"""Check every URL in hub/app/data/catalog.json (sites + radio streams).

Usage:  python scripts/check_links.py
Exit code 1 if any link looks dead. Some sites block bots (403/429) - those are reported as 'blocked?', not dead.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

CATALOG = Path(__file__).resolve().parents[1] / "hub" / "app" / "data" / "catalog.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PersonalMediaHub-LinkCheck/1.0",
           "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}


def check(item: tuple[str, str]) -> tuple[str, str, str]:
    name, url = item
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, stream=True, allow_redirects=True)
        code = r.status_code
        ctype = r.headers.get("content-type", "")
        r.close()
        if code < 400:
            return "ok", name, f"{code} {ctype.split(';')[0]}"
        if code in (401, 403, 429, 451) or code >= 500:
            return "blocked?", name, f"{code} {url}"
        return "DEAD", name, f"{code} {url}"
    except requests.RequestException as exc:
        return "DEAD", name, f"{exc.__class__.__name__} {url}"


def main() -> int:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    items = [(e["name"], e["url"]) for e in data["entries"]] + [(f"radio {r['name']}", r["url"]) for r in data["radios"]]
    with ThreadPoolExecutor(12) as ex:
        results = list(ex.map(check, items))
    for status, name, detail in sorted(results):
        print(f"{status:9} {name:45} {detail}")
    dead = [r for r in results if r[0] == "DEAD"]
    print(f"\n{len(results)} links checked, {len(dead)} dead")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
