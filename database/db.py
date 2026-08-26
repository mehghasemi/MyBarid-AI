"""دیتابیس SQLite محلی برنامه + ذخیره امن کلید API.

روی ویندوز، کلید API با Windows DPAPI (CryptProtectData/CryptUnprotectData)
رمزنگاری و در پوشه AppData کاربر ذخیره می‌شود؛ این رمزنگاری فقط برای همان
کاربر ویندوزی روی همان سیستم قابل بازگشایی است (دقیقاً همان روشی که در
اپ نمونه قبلی هم استفاده شده بود). روی سیستم‌عامل‌های دیگر (فقط برای توسعه/تست)
یک Fallback ساده و *غیر امن* استفاده می‌شود که باید در README مستند شود.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
from pathlib import Path

APP_NAME = "CRMQualityReviewer"
PORTABLE_DIR_NAME = "MyBarid-AI-Portable"


def _legacy_app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    else:
        base = Path.home() / ".local" / "share"
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _portable_app_data_dir() -> Path:
    override = os.environ.get("MYBARID_PORTABLE_DIR")
    if override:
        root = Path(override)
    elif getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parent.parent / PORTABLE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def app_data_dir() -> Path:
    """Return the portable data directory used by this installation.

    Existing AppData settings are migrated once, without deleting the
    original files. This keeps upgrades safe while making the EXE folder
    self-contained for transfer.
    """
    portable = _portable_app_data_dir()
    marker = portable / ".migrated-from-appdata"
    legacy = _legacy_app_data_dir()
    if not marker.exists() and legacy.resolve() != portable.resolve():
        import shutil

        for name in ("app.db", "api-key.bin", "criteria_config.json"):
            source = legacy / name
            target = portable / name
            if source.exists() and not target.exists():
                try:
                    shutil.copy2(source, target)
                except OSError:
                    pass
        marker.write_text("migrated\n", encoding="utf-8")
    return portable


DB_PATH = app_data_dir() / "app.db"
SECRET_PATH = app_data_dir() / "api-key.bin"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS ai_cache (
                signature TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_improvement_suggestions (
                signature TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_key TEXT NOT NULL,
                signature TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                source TEXT NOT NULL DEFAULT 'live',
                success INTEGER NOT NULL DEFAULT 1,
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ai_analysis_history_case
                ON ai_analysis_history(case_key, analyzed_at);
            CREATE TABLE IF NOT EXISTS crm_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                view_name TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                metadata TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_crm_snapshots_fetched
                ON crm_snapshots(fetched_at);
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default=None):
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]
    finally:
        conn.close()


def set_setting(key: str, value) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def get_ai_cache(signature: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT payload FROM ai_cache WHERE signature = ?", (signature,)).fetchone()
        return json.loads(row["payload"]) if row else None
    finally:
        conn.close()


def set_ai_cache(signature: str, payload: dict) -> None:
    import datetime

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO ai_cache(signature, payload, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(signature) DO UPDATE SET payload=excluded.payload, created_at=excluded.created_at",
            (signature, json.dumps(payload, ensure_ascii=False), datetime.datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def clear_ai_cache() -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM ai_cache")
        conn.commit()
    finally:
        conn.close()


def save_crm_snapshot(source: str, view_name: str, fetched_at: str,
                      metadata: dict, payload: dict) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO crm_snapshots(source, view_name, fetched_at, metadata, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, view_name, fetched_at, json.dumps(metadata, ensure_ascii=False),
             json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_crm_snapshot() -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT source, view_name, fetched_at, metadata, payload "
            "FROM crm_snapshots ORDER BY fetched_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {
            "source": row["source"], "view_name": row["view_name"],
            "fetched_at": row["fetched_at"],
            "metadata": json.loads(row["metadata"]),
            "payload": json.loads(row["payload"]),
        }
    except (json.JSONDecodeError, TypeError):
        return None
    finally:
        conn.close()


def record_ai_analysis(
    case_key: str, signature: str, provider: str, model: str,
    source: str = "live", success: bool = True, error: str | None = None,
    analyzed_at: str | None = None,
) -> str:
    from datetime import datetime, timezone

    timestamp = analyzed_at or datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO ai_analysis_history
                (case_key, signature, analyzed_at, provider, model, source, success, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (case_key, signature, timestamp, provider, model, source, int(success), error),
        )
        conn.commit()
        return timestamp
    finally:
        conn.close()


def get_latest_ai_analysis(case_key: str, signature: str | None = None) -> dict | None:
    conn = get_connection()
    try:
        if signature:
            row = conn.execute(
                """
                SELECT case_key, signature, analyzed_at, provider, model, source, success, error
                FROM ai_analysis_history
                WHERE case_key = ? AND signature = ?
                ORDER BY analyzed_at DESC, id DESC LIMIT 1
                """,
                (case_key, signature),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT case_key, signature, analyzed_at, provider, model, source, success, error
                FROM ai_analysis_history
                WHERE case_key = ?
                ORDER BY analyzed_at DESC, id DESC LIMIT 1
                """,
                (case_key,),
            ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def has_successful_ai_analysis(case_key: str, signature: str) -> bool:
    """Return whether this exact Case/settings signature has a successful AI tag."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM ai_analysis_history
            WHERE case_key = ? AND signature = ? AND success = 1
            ORDER BY analyzed_at DESC, id DESC
            LIMIT 1
            """,
            (case_key, signature),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_ai_suggestions(signature: str) -> list[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT payload FROM ai_improvement_suggestions WHERE signature = ?",
            (signature,),
        ).fetchone()
        if not row:
            return []
        payload = json.loads(row["payload"])
        return payload if isinstance(payload, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
    finally:
        conn.close()


def set_ai_suggestions(signature: str, suggestions: list[dict]) -> None:
    import datetime

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO ai_improvement_suggestions(signature, payload, created_at) "
            "VALUES (?, ?, ?) ON CONFLICT(signature) DO UPDATE SET "
            "payload=excluded.payload, created_at=excluded.created_at",
            (signature, json.dumps(suggestions, ensure_ascii=False),
             datetime.datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------ Secret key --

def _win_protect(value: str) -> bytes:
    from ctypes import POINTER, Structure, byref, c_byte, c_void_p, cast, string_at, windll
    from ctypes.wintypes import DWORD

    class DataBlob(Structure):
        _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_byte))]

    raw = value.encode("utf-8")
    source_buffer = (c_byte * len(raw)).from_buffer_copy(raw)
    source, target = DataBlob(len(raw), source_buffer), DataBlob()
    if not windll.crypt32.CryptProtectData(byref(source), None, None, None, None, 0, byref(target)):
        raise OSError("Windows DPAPI نتوانست کلید را رمزنگاری کند.")
    try:
        return string_at(target.pbData, target.cbData)
    finally:
        windll.kernel32.LocalFree(cast(target.pbData, c_void_p))


def _win_unprotect(value: bytes) -> str:
    from ctypes import POINTER, Structure, byref, c_byte, c_void_p, cast, string_at, windll
    from ctypes.wintypes import DWORD

    class DataBlob(Structure):
        _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_byte))]

    source_buffer = (c_byte * len(value)).from_buffer_copy(value)
    source, target = DataBlob(len(value), source_buffer), DataBlob()
    if not windll.crypt32.CryptUnprotectData(byref(source), None, None, None, None, 0, byref(target)):
        raise OSError("کلید ذخیره‌شده برای این کاربر ویندوز قابل خواندن نیست.")
    try:
        return string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        windll.kernel32.LocalFree(cast(target.pbData, c_void_p))


def save_api_key(value: str) -> None:
    if sys.platform == "win32":
        SECRET_PATH.write_bytes(_win_protect(value))
    else:
        # Fallback غیرامن، فقط برای توسعه روی غیر ویندوز. در README تصریح می‌شود.
        SECRET_PATH.write_bytes(base64.b64encode(value.encode("utf-8")))


def load_api_key() -> str:
    if not SECRET_PATH.exists():
        return ""
    try:
        if sys.platform == "win32":
            return _win_unprotect(SECRET_PATH.read_bytes())
        return base64.b64decode(SECRET_PATH.read_bytes()).decode("utf-8")
    except OSError:
        return ""


def delete_api_key() -> None:
    if SECRET_PATH.exists():
        SECRET_PATH.unlink()


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return key[:4] + "•" * (len(key) - 8) + key[-4:]
