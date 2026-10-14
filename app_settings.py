"""Shared connection settings; preserve legacy values for reversible migration."""
from urllib.parse import urlparse
from database import db


DEFAULT_CONNECTION = {"base_url": "https://crm.baridsoft.ir", "organization": "Main", "api_version": "v9.1"}


def main_settings():
    stored = db.get_setting("main_settings")
    if not isinstance(stored, dict):
        legacy = db.get_setting("crm_settings", {}) or {}
        stored = {"crm": {key: legacy.get(key) or value for key, value in DEFAULT_CONNECTION.items()}}
        db.set_setting("main_settings", stored)
    return stored


class MainSettingsMixin:
    def get_main_settings(self):
        return {"ok": True, **main_settings(), "storage_path": str(db.app_data_dir()),
                "connection_scope": "shared", "credentials": "Windows جاری یا ورود موقت؛ رمز ذخیره نمی‌شود"}

    def save_main_settings(self, payload):
        if any(getattr(self, name, {}).get("running") for name in ("_planning_status", "_crm_sync_status", "status")):
            return {"ok": False, "error": "تا پایان دریافت یا تحلیل، اتصال اصلی را تغییر ندهید."}
        crm = payload.get("crm") if isinstance(payload, dict) else None
        if not isinstance(crm, dict):
            return {"ok": False, "error": "ساختار تنظیمات CRM معتبر نیست."}
        checked = {key: str(crm.get(key) or "").strip() for key in DEFAULT_CONNECTION}
        parsed = urlparse(checked["base_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return {"ok": False, "error": "آدرس CRM باید http/https معتبر و بدون اطلاعات ورود باشد."}
        if not checked["organization"] or not checked["api_version"].startswith("v"):
            return {"ok": False, "error": "نام سازمان و نسخه API معتبر لازم است."}
        checked["base_url"] = checked["base_url"].rstrip("/")
        checked["organization"] = checked["organization"].strip("/")
        stored = main_settings()
        stored["crm"] = checked
        db.set_setting("main_settings", stored)
        return {"ok": True, "message": "اتصال اصلی ذخیره شد؛ Viewهای ماژول‌ها تغییر نکردند."}

    def get_evaluation_module_settings(self):
        return {"ok": True, "ai_enabled": db.get_setting("evaluation_ai_enabled", True)}

    def save_evaluation_module_settings(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("ai_enabled"), bool):
            return {"ok": False, "error": "تنظیم فعال‌بودن AI معتبر نیست."}
        db.set_setting("evaluation_ai_enabled", payload["ai_enabled"])
        return {"ok": True}
