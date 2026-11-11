"""Tiny internal HTTP API + scheduler. Only reachable from the Docker network (no published port).

GET  /health          -> {"ok": true}
GET  /report          -> last run report
GET  /reports         -> list of saved reports
GET  /queues          -> files waiting in _Review and _Duplicates (with reasons)
POST /run             -> body {"dry_run": true|false}; runs a pass and returns the report
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import from_env
from .engine import Organizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("organizer")

CFG = from_env()
ORG = Organizer(CFG)
MODE = os.environ.get("ORGANIZER_MODE", "dry-run").lower()   # dry-run | live | off
INTERVAL = int(os.environ.get("ORGANIZER_INTERVAL_MINUTES", "10"))


def list_queue(root: Path) -> list[dict]:
    notes_path = CFG.state_dir / "queue_notes.json"
    try:
        notes = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        notes = {}
    out = []
    if root.exists():
        for dirpath, _, files in os.walk(root):
            for f in files:
                p = Path(dirpath) / f
                rel = str(p.relative_to(CFG.media_root)).replace("\\", "/")
                try:
                    st = p.stat()
                except OSError:
                    continue
                out.append({"path": rel, "size": st.st_size, "modified": st.st_mtime, "reason": notes.get(rel, "")})
    return sorted(out, key=lambda x: -x["modified"])


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quieter logs
        log.debug(fmt, *args)

    def do_GET(self):
        reports = CFG.state_dir / "reports"
        if self.path == "/health":
            return self._send({"ok": True, "mode": MODE, "interval_minutes": INTERVAL})
        if self.path == "/report":
            try:
                return self._send(json.loads((reports / "last.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return self._send({"message": "no run yet"})
        if self.path == "/reports":
            files = sorted((p.name for p in reports.glob("2*.json")), reverse=True)[:50] if reports.exists() else []
            return self._send({"reports": files})
        if self.path.startswith("/reports/"):
            name = Path(self.path.split("/", 2)[2]).name
            try:
                return self._send(json.loads((reports / name).read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return self._send({"error": "not found"}, 404)
        if self.path == "/queues":
            return self._send({"review": list_queue(CFG.review), "duplicates": list_queue(CFG.duplicates)})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/run":
            return self._send({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        dry_run = bool(body.get("dry_run", True))
        report = ORG.run(dry_run=dry_run)
        self._send(report, 409 if report.get("status") == "busy" else 200)


def scheduler():
    time.sleep(15)
    while True:
        if MODE in {"dry-run", "live"}:
            try:
                r = ORG.run(dry_run=(MODE != "live"))
                if r.get("items"):
                    log.info("run %s (%s): %s", r.get("run_id"), MODE, r.get("counts"))
            except Exception:
                log.exception("scheduled run failed")
        time.sleep(max(1, INTERVAL) * 60)


def main():
    CFG.ensure_dirs()
    threading.Thread(target=scheduler, daemon=True).start()
    log.info("organizer API on :8000, mode=%s, every %s min, media=%s", MODE, INTERVAL, CFG.media_root)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()


if __name__ == "__main__":
    main()
