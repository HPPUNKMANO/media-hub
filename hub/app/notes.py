"""Tasks (with reminders sent as phone notifications) and daily Notes.

Reminders are real Web Push notifications: they arrive even when the hub app is closed, as long as the
phone has the hub installed on its Home Screen (iPhone: iOS 16.4+, opened from the https Tailscale address)
and notifications were allowed once. A reminder is only sent if its task is still not done.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .auth import uid

router = APIRouter()
DATA_DIR = Path(os.environ.get("HUB_DATA_DIR", "/data"))
MAX_TEXT = 500
MAX_NOTE = 50_000


# ----------------------------------------------------------------- storage
def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / "hub.db")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, done_at REAL);
        CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            due REAL NOT NULL, sent INTEGER NOT NULL DEFAULT 0);   -- sent: 0 waiting, 1 sent, 2 skipped (task done)
        CREATE TABLE IF NOT EXISTS notes (day TEXT PRIMARY KEY, body TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
    """)
    # later columns: which list a task is on (todo / shopping) and daily repeating reminders
    # each account has its own tasks, notes and devices (data from before accounts belongs to account 1)
    for table, col, ddl in (("tasks", "list", "TEXT NOT NULL DEFAULT 'todo'"), ("reminders", "repeat", "TEXT"),
                            ("tasks", "user_id", "INTEGER NOT NULL DEFAULT 1"), ("push_subs", "user_id", "INTEGER NOT NULL DEFAULT 1")):
        if col not in [r[1] for r in con.execute(f"PRAGMA table_info({table})")]:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    if "user_id" not in [r[1] for r in con.execute("PRAGMA table_info(notes)")]:
        con.executescript("""
            CREATE TABLE notes2 (user_id INTEGER NOT NULL, day TEXT NOT NULL, body TEXT NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY (user_id, day));
            INSERT INTO notes2 SELECT 1, day, body, updated FROM notes;
            DROP TABLE notes; ALTER TABLE notes2 RENAME TO notes;""")
    con.commit()
    return con


def _own(con: sqlite3.Connection, task_id: int, user: int) -> None:
    if not con.execute("SELECT 1 FROM tasks WHERE id=? AND user_id=?", (task_id, user)).fetchone():
        con.close()
        raise HTTPException(404, "unknown task")


LISTS = ("todo", "shopping")


def _list(value) -> str:
    return value if value in LISTS else "todo"


def _repeat(value) -> str | None:
    return "daily" if value == "daily" else None


def _task_out(con: sqlite3.Connection, row: sqlite3.Row) -> dict:
    rems = con.execute("SELECT id, due, sent, repeat FROM reminders WHERE task_id=? ORDER BY due", (row["id"],)).fetchall()
    return {"id": row["id"], "text": row["text"], "done": bool(row["done"]), "created": row["created"], "list": row["list"],
            "done_at": row["done_at"], "reminders": [dict(r) for r in rems]}


def _clean_text(value) -> str:
    text = " ".join(str(value or "").split())[:MAX_TEXT]
    if not text:
        raise HTTPException(400, "The task is empty.")
    return text


def _due_from(body: dict) -> float:
    """A reminder is given either as minutes from now or as an absolute time (epoch seconds)."""
    now = time.time()
    if body.get("minutes") is not None:
        minutes = float(body["minutes"])
        if not 1 <= minutes <= 60 * 24 * 60:
            raise HTTPException(400, "A reminder must be between 1 minute and 60 days away.")
        return now + minutes * 60
    at = float(body.get("at") or 0)
    if not now - 60 < at < now + 86400 * 366:
        raise HTTPException(400, "Pick a time in the future.")
    return max(at, now + 5)


async def _json(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "bad request body")
    if not isinstance(data, dict):
        raise HTTPException(400, "bad request body")
    return data


# ----------------------------------------------------------------- tasks
@router.get("/api/tasks")
async def list_tasks(request: Request, list: str = ""):
    con = db()
    where, args = ("WHERE user_id=? AND list=?", (uid(request), list)) if list in LISTS else ("WHERE user_id=?", (uid(request),))
    rows = con.execute(f"SELECT * FROM tasks {where} ORDER BY done, CASE WHEN done THEN -done_at ELSE created END DESC", args).fetchall()
    out = [_task_out(con, r) for r in rows]
    con.close()
    return {"tasks": out, "now": time.time()}


@router.post("/api/tasks")
async def add_task(request: Request):
    body = await _json(request)
    text = _clean_text(body.get("text"))
    con = db()
    cur = con.execute("INSERT INTO tasks(text, created, list, user_id) VALUES(?, ?, ?, ?)",
                      (text, time.time(), _list(body.get("list")), uid(request)))
    if body.get("minutes") is not None or body.get("at"):
        con.execute("INSERT INTO reminders(task_id, due, repeat) VALUES(?, ?, ?)",
                    (cur.lastrowid, _due_from(body), _repeat(body.get("repeat"))))
    con.commit()
    task = _task_out(con, con.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone())
    con.close()
    return task


@router.patch("/api/tasks/{task_id}")
async def edit_task(task_id: int, request: Request):
    body = await _json(request)
    con = db()
    _own(con, task_id, uid(request))
    if "text" in body:
        con.execute("UPDATE tasks SET text=? WHERE id=?", (_clean_text(body["text"]), task_id))
    if "done" in body:
        done = bool(body["done"])
        con.execute("UPDATE tasks SET done=?, done_at=? WHERE id=?", (int(done), time.time() if done else None, task_id))
    con.commit()
    task = _task_out(con, con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    con.close()
    return task


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int, request: Request):
    con = db()
    _own(con, task_id, uid(request))
    con.execute("DELETE FROM reminders WHERE task_id=?", (task_id,))
    con.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    con.commit()
    con.close()
    return {"ok": True}


@router.post("/api/tasks/{task_id}/reminders")
async def add_reminder(task_id: int, request: Request):
    body = await _json(request)
    due = _due_from(body)
    con = db()
    _own(con, task_id, uid(request))
    con.execute("INSERT INTO reminders(task_id, due, repeat) VALUES(?, ?, ?)", (task_id, due, _repeat(body.get("repeat"))))
    con.commit()
    task = _task_out(con, con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    con.close()
    return task


@router.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int, request: Request):
    con = db()
    con.execute("DELETE FROM reminders WHERE id=? AND task_id IN (SELECT id FROM tasks WHERE user_id=?)", (reminder_id, uid(request)))
    con.commit()
    con.close()
    return {"ok": True}


# ----------------------------------------------------------------- notes (one page per day)
def _check_day(day: str) -> str:
    import datetime as dt
    try:
        return dt.date.fromisoformat(day).isoformat()
    except ValueError:
        raise HTTPException(400, "bad date")


@router.get("/api/notes")
async def list_notes(request: Request):
    con = db()
    rows = con.execute("SELECT day, substr(body, 1, 160) AS preview, updated FROM notes WHERE user_id=? AND trim(body) != '' "
                       "ORDER BY day DESC LIMIT 120", (uid(request),)).fetchall()
    con.close()
    return {"days": [dict(r) for r in rows]}


@router.get("/api/notes/{day}")
async def get_note(day: str, request: Request):
    day = _check_day(day)
    con = db()
    row = con.execute("SELECT body, updated FROM notes WHERE user_id=? AND day=?", (uid(request), day)).fetchone()
    con.close()
    return {"day": day, "body": row["body"] if row else "", "updated": row["updated"] if row else None}


@router.put("/api/notes/{day}")
async def save_note(day: str, request: Request):
    day = _check_day(day)
    body = str((await _json(request)).get("body", ""))[:MAX_NOTE]
    con = db()
    con.execute("INSERT OR REPLACE INTO notes(user_id, day, body, updated) VALUES(?, ?, ?, ?)", (uid(request), day, body, time.time()))
    con.commit()
    con.close()
    return {"ok": True, "updated": time.time()}


# ----------------------------------------------------------------- web push
def _vapid():
    """The server's push identity, created once and kept in the hub database."""
    from py_vapid import Vapid
    con = db()
    row = con.execute("SELECT v FROM kv WHERE k='vapid_pem'").fetchone()
    if row and row[0]:
        con.close()
        return Vapid.from_pem(row[0].encode())
    v = Vapid()
    v.generate_keys()
    con.execute("INSERT OR REPLACE INTO kv(k, v) VALUES('vapid_pem', ?)", (v.private_pem().decode(),))
    con.commit()
    con.close()
    return v


def _public_key() -> str:
    from cryptography.hazmat.primitives import serialization
    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@router.get("/api/push/key")
async def push_key():
    return {"key": await asyncio.to_thread(_public_key)}


@router.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    sub = await _json(request)
    from urllib.parse import urlparse
    host = urlparse(str(sub.get("endpoint", ""))).hostname or ""
    push_hosts = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com", "notify.windows.com",
                  "push.services.mozilla.com", "android.googleapis.com")
    if not str(sub.get("endpoint", "")).startswith("https://") or not sub.get("keys") \
            or not any(host == h or host.endswith("." + h) for h in push_hosts):
        raise HTTPException(400, "bad subscription")
    con = db()
    con.execute("INSERT OR REPLACE INTO push_subs(endpoint, data, created, user_id) VALUES(?, ?, ?, ?)",
                (sub["endpoint"], json.dumps(sub), time.time(), uid(request)))
    con.commit()
    count = con.execute("SELECT count(*) FROM push_subs WHERE user_id=?", (uid(request),)).fetchone()[0]
    con.close()
    return {"ok": True, "devices": count}


@router.get("/api/push/status")
async def push_status(request: Request):
    con = db()
    count = con.execute("SELECT count(*) FROM push_subs WHERE user_id=?", (uid(request),)).fetchone()[0]
    con.close()
    return {"devices": count}


def _send_all(payload: dict, user: int) -> int:
    """Send one notification to every device of one account; forget devices that unsubscribed. Returns devices reached."""
    from pywebpush import WebPushException, webpush
    con = db()
    subs = con.execute("SELECT endpoint, data FROM push_subs WHERE user_id=?", (user,)).fetchall()
    con.close()
    vapid = _vapid()
    claim = os.environ.get("HUB_LAN_URL") or "mailto:media-hub@localhost.localdomain"
    reached, gone = 0, []
    for s in subs:
        try:
            webpush(json.loads(s["data"]), json.dumps(payload), vapid_private_key=vapid,
                    vapid_claims={"sub": claim}, ttl=3600, timeout=10)
            reached += 1
        except WebPushException as exc:
            code = getattr(exc.response, "status_code", 0)
            if code in (404, 410):
                gone.append(s["endpoint"])
            print(f"[push] failed ({code}): {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad device must not stop the others
            print(f"[push] failed: {exc!r}", flush=True)
    if gone:
        con = db()
        con.executemany("DELETE FROM push_subs WHERE endpoint=?", [(g,) for g in gone])
        con.commit()
        con.close()
    return reached


@router.post("/api/push/test")
async def push_test(request: Request):
    reached = await asyncio.to_thread(_send_all, {"title": "Media Hub", "body": "Notifications work. Reminders will arrive here.",
                                                  "url": "/#tasks", "tag": "test"}, uid(request))
    return {"reached": reached}


# ----------------------------------------------------------------- reminder loop
def _fire_due() -> None:
    con = db()
    now = time.time()
    due = con.execute("SELECT r.id, r.task_id, r.due, r.repeat, t.text, t.done, t.done_at, t.user_id FROM reminders r "
                      "JOIN tasks t ON t.id = r.task_id WHERE r.sent = 0 AND r.due <= ?", (now,)).fetchall()
    con.close()
    for r in due:
        status = 2
        done = r["done"]
        if r["repeat"] == "daily":
            # a daily habit: ticked on an earlier day = to do again today; then schedule tomorrow's alarm
            con = db()
            if done and (r["done_at"] or 0) < r["due"] - 12 * 3600:
                con.execute("UPDATE tasks SET done=0, done_at=NULL WHERE id=?", (r["task_id"],))
                done = 0
            nxt = r["due"] + 86400
            while nxt <= now:
                nxt += 86400
            con.execute("INSERT INTO reminders(task_id, due, repeat) VALUES(?, ?, 'daily')", (r["task_id"], nxt))
            con.commit()
            con.close()
        if not done:
            _send_all({"title": "⏰ To do", "body": r["text"], "url": "/#tasks", "tag": f"task-{r['task_id']}"}, r["user_id"])
            status = 1
        con = db()
        con.execute("UPDATE reminders SET sent=? WHERE id=?", (status, r["id"]))
        con.commit()
        con.close()


async def _loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_fire_due)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            print(f"[reminders] {exc!r}", flush=True)
        await asyncio.sleep(15)


def start() -> None:
    asyncio.get_event_loop().create_task(_loop())
