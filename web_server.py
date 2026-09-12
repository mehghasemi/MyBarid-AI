"""سرور وب چندکاربره داخلی با SQLite مرکزی و احراز هویت محلی."""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.cookies
import json
import os
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from database import db

SESSION_COOKIE = "mybarid_session"
SESSION_TTL = 8 * 60 * 60
USERS_FILE = db.app_data_dir() / "web-users.json"

ROLE_PERMISSIONS = {
    "admin": {"*"},
    "analyst": {
        "get_version", "get_changelog", "get_crm_settings", "get_dataset_info", "get_analysis_info",
        "get_crm_sync_status", "get_dataset_case_keys", "get_dataset_cases", "start_analysis",
        "cancel_analysis", "get_status", "get_dashboard", "get_comparison", "get_ranking",
        "get_expert_detail", "get_expert_report", "get_case_detail", "get_cases_table",
        "get_suspicious", "get_data_quality", "get_management_report", "get_current_user",
    },
    "viewer": {
        "get_version", "get_changelog", "get_crm_settings", "get_dataset_info", "get_analysis_info",
        "get_dashboard", "get_comparison", "get_ranking", "get_expert_detail", "get_expert_report",
        "get_case_detail", "get_cases_table", "get_suspicious", "get_data_quality",
        "get_management_report", "get_current_user",
    },
}


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return "pbkdf2_sha256$210000$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
        return algorithm == "pbkdf2_sha256" and hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


class WebApplication:
    def __init__(self, api, static_dir: Path):
        self.api = api
        self.static_dir = static_dir
        self.users = self._load_users()
        self.sessions: dict[str, tuple[str, float]] = {}
        self.lock = threading.Lock()
        self.operation_lock = threading.Lock()

    @staticmethod
    def _load_users() -> dict:
        if not USERS_FILE.exists():
            return {"users": {}}
        try:
            data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data.get("users"), dict) else {"users": {}}
        except (OSError, json.JSONDecodeError):
            return {"users": {}}

    def save_users(self):
        USERS_FILE.write_text(json.dumps(self.users, ensure_ascii=False, indent=2), encoding="utf-8")

    def setup(self, username: str, password: str, analyst_username: str = "", analyst_password: str = "") -> bool:
        if self.users.get("users") or len(username) < 3 or len(password) < 8:
            return False
        if analyst_username or analyst_password:
            if len(analyst_username) < 3 or len(analyst_password) < 8 or analyst_username == username:
                return False
        self.users["users"][username] = {"password_hash": _hash_password(password), "role": "admin", "display_name": username}
        if analyst_username or analyst_password:
            self.users["users"][analyst_username] = {"password_hash": _hash_password(analyst_password), "role": "analyst", "display_name": analyst_username}
        self.save_users()
        return True

    def login(self, username: str, password: str) -> str | None:
        record = (self.users.get("users") or {}).get(username)
        if not record or not _verify_password(password, str(record.get("password_hash") or "")):
            return None
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token] = (username, time.time())
        return token

    def user(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self.lock:
            session = self.sessions.get(token)
            if not session or time.time() - session[1] > SESSION_TTL:
                self.sessions.pop(token, None)
                return None
        record = (self.users.get("users") or {}).get(session[0])
        return {"username": session[0], "display_name": record.get("display_name", session[0]), "role": record.get("role", "viewer")} if record else None

    def call(self, user: dict, method: str, args: list):
        permissions = ROLE_PERMISSIONS.get(user["role"], set())
        if method.startswith("_") or ("*" not in permissions and method not in permissions):
            raise PermissionError("دسترسی شما به این عملیات مجاز نیست.")
        target = getattr(self.api, method, None)
        if not callable(target):
            raise AttributeError("عملیات در Backend پیدا نشد.")
        if method in {"start_analysis", "sync_crm_view"}:
            if not self.operation_lock.acquire(False):
                raise RuntimeError("عملیات دیگری در حال اجراست؛ لطفاً تا پایان آن صبر کنید.")
            try:
                return target(*args)
            finally:
                self.operation_lock.release()
        return target(*args)


def _auth_page(setup=False, error="") -> bytes:
    title = "راه‌اندازی کاربران" if setup else "ورود به MyBarid-AI"
    description = "در اولین اجرا، حساب مدیر را بسازید." if setup else "برای ورود، اطلاعات کاربری خود را وارد کنید."
    action = "/setup" if setup else "/login"
    extra = ('<hr><p>حساب تحلیل‌گر (اختیاری)</p><label>نام کاربری تحلیل‌گر</label>'
             '<input name="analyst_username" minlength="3"><label>رمز تحلیل‌گر (حداقل ۸ نویسه)</label>'
             '<input name="analyst_password" type="password" minlength="8">') if setup else ""
    message = f'<div class="error">{error}</div>' if error else ""
    return f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>{title}</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f8fafc;font-family:Tahoma,Arial;color:#0f172a}}main{{width:min(410px,calc(100% - 32px));background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:28px;box-shadow:0 8px 30px #0f172a18}}h1{{font-size:22px}}p,label{{font-size:13px}}p{{color:#64748b}}label{{display:block;margin:15px 0 6px}}input,select{{box-sizing:border-box;width:100%;padding:11px;border:1px solid #cbd5e1;border-radius:8px;font:inherit}}button{{width:100%;margin-top:20px;padding:11px;border:0;border-radius:8px;background:#4f46e5;color:white;font:inherit}}.error{{margin-top:14px;color:#b91c1c;background:#fef2f2;padding:10px;border-radius:8px;font-size:13px}}</style>
<main><h1>{title}</h1><p>{description}</p><form method="post" action="{action}"><label>نام کاربری</label><input name="username" minlength="3" required><label>رمز عبور (حداقل ۸ نویسه)</label><input name="password" type="password" minlength="8" required>{extra}<button>{"ساخت حساب مدیر" if setup else "ورود"}</button></form>{message}</main></html>'''.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def app(self):
        return self.server.application  # type: ignore[attr-defined]

    def token(self):
        cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return cookies.get(SESSION_COOKIE).value if cookies.get(SESSION_COOKIE) else None

    def current_user(self):
        return self.app().user(self.token())

    def send_bytes(self, status, body, content_type="text/html; charset=utf-8", headers=None):
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items(): self.send_header(key, value)
        self.end_headers(); self.wfile.write(body)

    def send_json(self, status, data):
        self.send_bytes(status, json.dumps(data, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/login":
            self.send_bytes(200, _auth_page(False)) if self.app().users["users"] else self.send_bytes(303, b"", headers={"Location": "/setup"}); return
        if path == "/setup":
            self.send_bytes(200, _auth_page(True)); return
        if path == "/logout":
            with self.app().lock: self.app().sessions.pop(self.token() or "", None)
            self.send_bytes(303, b"", headers={"Location": "/login"}); return
        if not self.current_user(): self.send_bytes(303, b"", headers={"Location": "/login"}); return
        relative = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        if ".." in Path(relative).parts: self.send_bytes(404, b"Not found"); return
        file_path = self.app().static_dir / relative
        if not file_path.is_file(): self.send_bytes(404, b"Not found"); return
        content_type = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}.get(file_path.suffix, "application/octet-stream")
        self.send_bytes(200, file_path.read_bytes(), content_type)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0")); raw = self.rfile.read(length); path = urlparse(self.path).path
        if path in {"/login", "/setup"}:
            form = parse_qs(raw.decode("utf-8", errors="replace")); username = (form.get("username") or [""])[0].strip(); password = (form.get("password") or [""])[0]
            if path == "/setup":
                if not self.app().setup(username, password, (form.get("analyst_username") or [""])[0].strip(), (form.get("analyst_password") or [""])[0]): self.send_bytes(400, _auth_page(True, "اطلاعات حساب نامعتبر است یا راه‌اندازی قبلاً انجام شده.")); return
                token = self.app().login(username, password)
            else: token = self.app().login(username, password)
            if not token: self.send_bytes(401, _auth_page(False, "نام کاربری یا رمز عبور نادرست است.")); return
            self.send_bytes(303, b"", headers={"Location": "/", "Set-Cookie": f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax"}); return
        if path != "/api/call": self.send_json(404, {"ok": False, "error": "مسیر پیدا نشد."}); return
        user = self.current_user()
        if not user: self.send_json(401, {"ok": False, "error": "نشست ورود منقضی شده است."}); return
        try:
            request = json.loads(raw.decode("utf-8")); method = str(request.get("method") or ""); args = request.get("args") or []
            result = {"ok": True, "user": user} if method == "get_current_user" else self.app().call(user, method, args)
            self.send_json(200, {"ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001
            self.send_json(403 if isinstance(exc, PermissionError) else 400, {"ok": False, "error": str(exc)})


def run_web_server(api, host="127.0.0.1", port=42001, static_dir=None):
    if host not in {"127.0.0.1", "localhost", "::1"}:
        if os.environ.get("MYBARID_WEB_ALLOW_NETWORK") != "1":
            raise RuntimeError("برای دسترسی شبکه‌ای، متغیر MYBARID_WEB_ALLOW_NETWORK=1 را صریحاً تنظیم کنید.")
    server = ThreadingHTTPServer((host, int(port)), Handler)
    server.application = WebApplication(api, static_dir or Path(__file__).resolve().parent / "ui")  # type: ignore[attr-defined]
    print(f"MyBarid-AI web server: http://{host}:{port}")
    print(f"فایل کاربران: {USERS_FILE}")
    server.serve_forever()
