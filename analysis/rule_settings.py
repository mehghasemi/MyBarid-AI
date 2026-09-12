"""Configurable business-rule settings used by the Rule-Based analysis."""
from __future__ import annotations

from copy import deepcopy


DEFAULT_ANALYSIS_RULES = {
    "keywords": {
        "problem": ["مشکل", "خطا", "ایراد", "قطع", "کند", "مسدود", "خرابی", "عدم", "امکان لاگین"],
        "action": ["بررسی", "اقدام", "تماس گرفته شد", "انجام شد", "پیگیری", "تنظیم", "نصب", "اصلاح", "ریست", "تغییر"],
        "result": ["حل شد", "رفع شد", "برطرف شد", "نتیجه", "تست شد", "تایید شد", "کار می‌کند", "مشکل برطرف"],
        "l2": ["l2", "level 2", "second level", "tier 2", "لایه دو", "لایه ۲", "سطح دو", "سطح ۲", "ارجاع به لایه"],
    },
    "thresholds": {
        "notes_clarity_very_short": 20,
        "notes_clarity_short": 50,
        "notes_clarity_good": 150,
        "notes_writing_very_short_words": 3,
        "notes_writing_short_words": 8,
        "notes_writing_good_words": 20,
        "first_response_fast_hours": 4,
        "first_response_normal_hours": 24,
        "first_response_late_hours": 72,
        "followup_on_time_days": 1,
        "followup_delayed_days": 3,
        "due_date_grace_hours": 24,
        "scenario_min_chars": 15,
        "open_event_gap_days": 14,
        "closed_event_gap_days": 30,
        "data_health_event_gap_days": 180,
    },
    "data_health": {
        "notes_without_description": True, "tasks_without_description": True,
        "cases_without_note": True, "cases_without_task": True, "duplicate_notes": True,
        "duplicate_tasks": True, "unmatched_tasks": True, "unreasonable_timestamps": True,
    },
}

RULE_SETTING_INFO = {
    "keywords": {"name_fa": "واژه‌های تشخیص متن", "description_fa": "واژه‌هایی که برای تشخیص مشکل، اقدام، نتیجه و ارجاع به لایه دوم در متن استفاده می‌شوند."},
    "thresholds": {"name_fa": "آستانه‌های Rule-Based", "description_fa": "مرزهای عددی مورد استفاده در امتیازدهی کیفیت یادداشت، زمان پاسخ، پیگیری و سلامت Timeline."},
}


def normalize_analysis_rules(value: dict | None) -> dict:
    result = deepcopy(DEFAULT_ANALYSIS_RULES)
    if not isinstance(value, dict):
        return result
    for section in ("keywords", "thresholds"):
        incoming = value.get(section)
        if not isinstance(incoming, dict):
            continue
        for key, default in result[section].items():
            if section == "keywords":
                items = incoming.get(key)
                if isinstance(items, list):
                    result[section][key] = [str(item).strip() for item in items if str(item).strip()]
            else:
                try:
                    number = float(incoming.get(key, default))
                    result[section][key] = int(number) if number.is_integer() else number
                except (TypeError, ValueError):
                    pass
    incoming_health = value.get("data_health")
    if isinstance(incoming_health, dict):
        for key in result["data_health"]:
            if key in incoming_health:
                result["data_health"][key] = bool(incoming_health[key])
    return result
