"""Accounts: everyone logs in; tasks, notes and notifications are per account.

- The first account is created from the setup screen (only possible from the PC / tailnet, never through the
  public Funnel address) and is the admin. Only the admin can add or remove accounts.
- Passwords are hashed with scrypt; a login gives a random session token in an HttpOnly cookie (1 year).
- Every /api route needs a session, except the few listed in OPEN.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()
DATA_DIR = Path(os.environ.get("HUB_DATA_DIR", "/data"))
COOKIE = "hub_session"
SESSION_DAYS = 3650   # "stay signed in": one login per device, valid 10 years
OPEN = ("/api/auth/", "/api/config")   # /api/config is read by the watchdog (ports only, nothing private)
_fails: dict[str, list[float]] = {}

# Tabs the main account can turn off for each person (home and account are always there).
TABS = [("watch", "Watch"), ("tv", "Live TV"), ("sport", "Sport"), ("sportrecap", "Résumé sport"), ("listen", "Listen"), ("journal", "Journal"),
        ("ai", "Récap IA"), ("notetask", "Note Task"), ("netflix", "Netflix"),
        ("discover", "Discover"), ("learn", "Learn"), ("organizer", "Organize"), ("offline", "Hors connexion"),
        ("status", "Status")]
TAB_KEYS = {k for k, _ in TABS}
# API routes that belong to a tab: a person without the tab gets 403, not just a hidden button.
API_TABS = [("/api/watch", "watch"), ("/api/img/jf", "watch"), ("/api/tv/", "tv"), ("/api/sportrecap", "sportrecap"), ("/api/sport", "sport"),
            ("/api/listen", "listen"), ("/api/nd/", "listen"), ("/api/img/nd", "listen"), ("/api/radio/", "listen"),
            ("/api/news", "journal"), ("/api/read", "journal"), ("/api/ai", "ai"), ("/api/tasks", "notetask"),
            ("/api/reminders", "notetask"), ("/api/notes", "notetask"),
            ("/api/organizer", "organizer"), ("/api/status", "status")]


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / "hub.db")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            pw TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL);
    """)
    if "hidden" not in {r[1] for r in con.execute("PRAGMA table_info(users)")}:
        con.execute("ALTER TABLE users ADD COLUMN hidden TEXT NOT NULL DEFAULT ''")   # tabs turned off, comma-separated
    # sessions are stored as SHA-256 of the cookie: a copy of the database can't be used to sign in.
    # Older rows (raw tokens) are converted in place, so nobody gets signed out.
    for (raw,) in con.execute("SELECT token FROM sessions WHERE length(token) != 64").fetchall():
        con.execute("UPDATE OR IGNORE sessions SET token=? WHERE token=?", (_th(raw), raw))
    con.commit()
    return con


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"{salt.hex()}${h.hex()}"


def _check(password: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(_hash(password, bytes.fromhex(salt)), stored)


def _public(request: Request) -> bool:
    """True when the request came through the public Funnel address (not the PC or the tailnet)."""
    return bool(request.headers.get("tailscale-funnel-request"))


def _ip(request: Request) -> str:
    """The address the proxy saw. Its entry is the LAST one; anything before it was written by the client itself."""
    xff = request.headers.get("x-forwarded-for")
    return xff.split(",")[-1].strip() if xff else (request.client.host if request.client else "")


_DUMMY = None


def _slow_no(password: str) -> None:
    """Same work as a real check, so a wrong name can't be told apart from a wrong password by timing."""
    global _DUMMY
    _DUMMY = _DUMMY or _hash("dummy-password")
    _check(password, _DUMMY)


def user_of(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    con = db()
    row = con.execute("SELECT u.id, u.name, u.admin, u.hidden FROM sessions s JOIN users u ON u.id = s.user_id "
                      "WHERE s.token=? AND s.created > ?", (_th(token), time.time() - SESSION_DAYS * 86400)).fetchone()
    con.close()
    return _user(row) if row else None


def _user(row) -> dict:
    u = dict(row)
    u["hidden"] = [] if u.get("admin") else [t for t in (u.get("hidden") or "").split(",") if t in TAB_KEYS]
    return u


def tab_of(path: str) -> str | None:
    return next((t for prefix, t in API_TABS if path.startswith(prefix)), None)


SECURITY_HEADERS = {
    "Content-Security-Policy": "frame-ancestors 'self'",   # no other site can show the hub in a hidden frame
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    # YouTube refuses to play an embedded video when it can't see which site embeds it (error 153,
    # "video player configuration error"): send the hub's address (origin only, never the page path).
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def _foreign(request: Request) -> bool:
    """True when another website (or another port of this machine) is trying to make the browser change something."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return False
    site = request.headers.get("sec-fetch-site")   # set by every modern browser, can't be forged by a web page
    if site and site not in ("same-origin", "none"):
        return True
    origin = request.headers.get("origin")
    if origin and origin != "null":
        from urllib.parse import urlparse
        hosts = {request.headers.get("host", ""), request.headers.get("x-forwarded-host", "")}
        return urlparse(origin).netloc not in hosts
    return False


async def middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and _foreign(request):
        return JSONResponse({"error": "request from another site refused"}, status_code=403, headers=SECURITY_HEADERS)
    if path.startswith("/api/") and not path.startswith(OPEN):
        user = user_of(request)
        if not user:
            resp = JSONResponse({"error": "login required"}, status_code=401)
            resp.headers.update(SECURITY_HEADERS)
            return resp
        request.state.user = user
        if tab_of(path) in user["hidden"]:
            resp = JSONResponse({"error": "this tab is turned off for your account"}, status_code=403)
            resp.headers.update(SECURITY_HEADERS)
            return resp
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


def uid(request: Request) -> int:
    return request.state.user["id"]


def need_admin(request: Request) -> None:
    if not request.state.user.get("admin"):
        raise HTTPException(403, "Only the main account can do this.")


def _clean_name(value) -> str:
    name = " ".join(str(value or "").split())[:40]
    if not name:
        raise HTTPException(400, "Enter a name.")
    return name


def _clean_pw(value) -> str:
    pw = str(value or "")
    if len(pw) < 6:
        raise HTTPException(400, "The password needs at least 6 characters.")
    return pw[:200]


def _login_response(request: Request, user_id: int) -> JSONResponse:
    token = secrets.token_urlsafe(32)
    con = db()
    con.execute("INSERT INTO sessions(token, user_id, created) VALUES(?, ?, ?)", (_th(token), user_id, time.time()))
    con.commit()
    con.close()
    resp = JSONResponse({"ok": True})
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=https)
    return resp


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "bad request body")
    return data if isinstance(data, dict) else {}


# ----------------------------------------------------------------- routes
@router.get("/api/auth/me")
async def me(request: Request):
    con = db()
    count = con.execute("SELECT count(*) FROM users").fetchone()[0]
    con.close()
    user = user_of(request)
    resp = JSONResponse({"user": user, "needs_setup": count == 0, "setup_allowed": count == 0 and not _public(request)})
    if user:   # every visit pushes the cookie's end date back: a signed-in device stays signed in
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp.set_cookie(COOKIE, request.cookies[COOKIE], max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=https)
        con = db()
        con.execute("UPDATE sessions SET created=? WHERE token=?", (time.time(), _th(request.cookies[COOKIE])))
        con.commit()
        con.close()
    return resp


@router.post("/api/auth/setup")
async def setup(request: Request):
    """Creates the first (admin) account. Refused once an account exists, and from the public address."""
    if _public(request):
        raise HTTPException(403, "Create the first account from your PC or phone on Tailscale.")
    body = await _body(request)
    name, pw = _clean_name(body.get("name")), _clean_pw(body.get("password"))
    con = db()
    if con.execute("SELECT count(*) FROM users").fetchone()[0]:
        con.close()
        raise HTTPException(409, "The main account already exists.")
    cur = con.execute("INSERT INTO users(name, pw, admin, created) VALUES(?, ?, 1, ?)", (name, _hash(pw), time.time()))
    con.commit()
    user_id = cur.lastrowid
    con.close()
    return _login_response(request, user_id)


@router.post("/api/auth/login")
async def login(request: Request):
    body = await _body(request)
    name = " ".join(str(body.get("name", "")).split())[:40]
    password = str(body.get("password", ""))
    ip, who, now = "ip:" + _ip(request), "name:" + name.lower(), time.time()
    # limits per address AND per account name: a fake address doesn't give more tries on an account
    for k, limit in ((ip, 8), (who, 10)):
        if len([t for t in _fails.get(k, []) if now - t < 900]) >= limit:
            raise HTTPException(429, "Too many tries. Wait 15 minutes.")
    if len(_fails) > 5000:   # forget old failures so random names can't fill the memory
        for k in [k for k, v in _fails.items() if not v or now - v[-1] > 900]:
            _fails.pop(k, None)
        if len(_fails) > 5000:
            _fails.clear()
    if len(password) > 200:   # scrypt on megabytes would burn the CPU
        raise HTTPException(401, "Wrong name or password.")
    con = db()
    row = con.execute("SELECT id, pw FROM users WHERE name=?", (name,)).fetchone()
    con.close()
    ok = _check(password, row["pw"]) if row else (_slow_no(password) or False)
    if not ok:
        for k in (ip, who):
            _fails[k] = [t for t in _fails.get(k, []) if now - t < 900] + [now]
        raise HTTPException(401, "Wrong name or password.")
    _fails.pop(ip, None)
    _fails.pop(who, None)
    return _login_response(request, row["id"])


@router.post("/api/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        con = db()
        con.execute("DELETE FROM sessions WHERE token=?", (_th(token),))
        con.commit()
        con.close()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


def _session_user(request: Request) -> dict:
    user = user_of(request)
    if not user:
        raise HTTPException(401, "login required")
    return user


@router.post("/api/auth/password")
async def change_password(request: Request):
    user = _session_user(request)
    body = await _body(request)
    con = db()
    row = con.execute("SELECT pw FROM users WHERE id=?", (user["id"],)).fetchone()
    if len(str(body.get("old", ""))) > 200 or not _check(str(body.get("old", "")), row["pw"]):
        con.close()
        raise HTTPException(400, "The current password is wrong.")
    con.execute("UPDATE users SET pw=? WHERE id=?", (_hash(_clean_pw(body.get("new"))), user["id"]))
    con.execute("DELETE FROM sessions WHERE user_id=? AND token != ?", (user["id"], _th(request.cookies.get(COOKIE, ""))))
    con.commit()
    con.close()
    return {"ok": True}


@router.get("/api/auth/users")
async def list_users(request: Request):
    user = _session_user(request)
    if not user["admin"]:
        raise HTTPException(403, "Only the main account can do this.")
    con = db()
    rows = con.execute("SELECT id, name, admin, created, hidden FROM users ORDER BY id").fetchall()
    con.close()
    return {"users": [_user(r) for r in rows], "tabs": [{"key": k, "label": l} for k, l in TABS]}


@router.put("/api/auth/users/{user_id}/tabs")
async def set_tabs(user_id: int, request: Request):
    """The main account chooses which tabs a person can open."""
    user = _session_user(request)
    if not user["admin"]:
        raise HTTPException(403, "Only the main account can do this.")
    body = await _body(request)
    hidden = body.get("hidden")
    if not isinstance(hidden, list):
        raise HTTPException(400, "hidden must be a list")
    clean = ",".join(sorted({str(t) for t in hidden} & TAB_KEYS))
    con = db()
    cur = con.execute("UPDATE users SET hidden=? WHERE id=? AND admin=0", (clean, user_id))
    con.commit()
    con.close()
    if not cur.rowcount:
        raise HTTPException(404, "No such account (the main account always sees everything).")
    return {"ok": True, "hidden": [t for t in clean.split(",") if t]}


@router.post("/api/auth/users")
async def add_user(request: Request):
    user = _session_user(request)
    if not user["admin"]:
        raise HTTPException(403, "Only the main account can do this.")
    body = await _body(request)
    name, pw = _clean_name(body.get("name")), _clean_pw(body.get("password"))
    con = db()
    try:
        con.execute("INSERT INTO users(name, pw, admin, created) VALUES(?, ?, 0, ?)", (name, _hash(pw), time.time()))
        con.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "This name is already taken.")
    finally:
        con.close()
    return {"ok": True}


@router.delete("/api/auth/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    user = _session_user(request)
    if not user["admin"]:
        raise HTTPException(403, "Only the main account can do this.")
    if user_id == user["id"]:
        raise HTTPException(400, "You can't delete your own account.")
    con = db()
    con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM users WHERE id=? AND admin=0", (user_id,))
    # their personal data goes with them
    for sql in ("DELETE FROM reminders WHERE task_id IN (SELECT id FROM tasks WHERE user_id=?)",
                "DELETE FROM tasks WHERE user_id=?", "DELETE FROM notes WHERE user_id=?", "DELETE FROM push_subs WHERE user_id=?"):
        try:
            con.execute(sql, (user_id,))
        except sqlite3.OperationalError:
            pass
    con.commit()
    con.close()
    return {"ok": True}
