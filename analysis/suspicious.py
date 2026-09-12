from __future__ import annotations

import re
from dataclasses import dataclass

from analysis.rules import RESULT_KEYWORDS, _contains_any, _staff_notes, _staff_text
from data.cleaner import CaseBundle


@dataclass
class SuspiciousCase:
    case_key: str
    case_number: str | None
    case_title: str | None
    reasons: list[str]


DEFAULT_SUSPICIOUS_RULES = {
    "closed_without_events": {"active": True, "threshold": 0},
    "closed_without_result": {"active": True, "threshold": 0},
    "tasks_without_description": {"active": True, "threshold": 0},
    "low_confidence_task_links": {"active": True, "threshold": 2},
    "long_event_gap": {"active": False, "threshold": 60},
    "multiple_notes_without_task": {"active": False, "threshold": 3},
    "short_notes_majority": {"active": False, "threshold": 15},
}

SUSPICIOUS_RULE_INFO = {
    "closed_without_events": {"name_fa": "مورد بسته‌شده بدون هیچ رویداد", "description_fa": "Case بسته یا حل‌شده است اما Note یا Task قابل بررسی ندارد.", "category_fa": "مستندسازی و شواهد", "severity": "زیاد"},
    "closed_without_result": {"name_fa": "مورد بسته‌شده بدون ثبت نتیجه اقدام", "description_fa": "Case بسته یا حل‌شده است اما نتیجه یا اقدام نهایی در رویدادها قابل تشخیص نیست.", "category_fa": "مستندسازی و شواهد", "severity": "زیاد"},
    "tasks_without_description": {"name_fa": "Task بدون توضیح قابل بررسی", "description_fa": "Task وجود دارد اما همه Taskهای متصل Description خالی یا فاقد متن هستند.", "category_fa": "کیفیت داده", "severity": "متوسط"},
    "low_confidence_task_links": {"name_fa": "ابهام در اتصال Task به Case", "description_fa": "چند Task با اطمینان پایین و تطبیق متنی به Case متصل شده‌اند.", "category_fa": "کیفیت داده", "severity": "متوسط"},
    "long_event_gap": {"name_fa": "فاصله زمانی غیرعادی بین رویدادها", "description_fa": "بین رویدادهای متوالی بیشتر از آستانه تعیین‌شده فاصله وجود دارد.", "category_fa": "پیگیری فرایند", "severity": "متوسط"},
    "multiple_notes_without_task": {"name_fa": "Noteهای متعدد بدون Task", "description_fa": "فقط بر اساس تعداد Note و نبود Task علامت‌گذاری می‌کند؛ پیش‌فرض غیرفعال است.", "category_fa": "قاعده سفارشی", "severity": "کم"},
    "short_notes_majority": {"name_fa": "غلبه Noteهای کوتاه", "description_fa": "بیش از نیمی از Noteها کوتاه‌تر از آستانه هستند؛ به‌تنهایی نشانه قطعی ضعف نیست.", "category_fa": "قاعده سفارشی", "severity": "کم"},
}


def normalized_rule_settings(settings: dict | None = None) -> dict:
    result = {key: dict(value) for key, value in DEFAULT_SUSPICIOUS_RULES.items()}
    for key, value in (settings or {}).items():
        if key not in result or not isinstance(value, dict):
            continue
        result[key]["active"] = bool(value.get("active", result[key]["active"]))
        try:
            result[key]["threshold"] = max(0, int(value.get("threshold", result[key]["threshold"])))
        except (TypeError, ValueError):
            pass
    return result


def normalize_reason(reason: str) -> str:
    """Return the stable filter key/label for a suspicious-case reason.

    Details that vary per case, such as the measured number of days, must not
    create separate filter options for the same rule.
    """
    text = " ".join((reason or "").split())
    text = re.sub(r"\s*\(\s*\d+\s*روز\s*\)", "", text)
    text = re.sub(r"\s*\(\s*\d+\s*days?\s*\)", "", text, flags=re.IGNORECASE)
    return text.strip()


def find_suspicious_cases(cases: dict[str, CaseBundle], rule_settings: dict | None = None) -> list[SuspiciousCase]:
    rules = normalized_rule_settings(rule_settings)
    flagged: list[SuspiciousCase] = []
    for key, case in cases.items():
        reasons: list[str] = []
        staff_notes = _staff_notes(case)

        closed = (case.status or "").casefold() in {"resolved", "closed"}
        if rules["closed_without_events"]["active"] and closed and not case.all_events_sorted:
            reasons.append("مورد بسته یا حل‌شده بدون هیچ رویداد قابل بررسی")

        if rules["multiple_notes_without_task"]["active"] and len(staff_notes) >= rules["multiple_notes_without_task"]["threshold"] and not case.tasks:
            reasons.append("Note های متعدد ولی بدون هیچ Task")

        if rules["tasks_without_description"]["active"] and case.tasks and all(not (t.description or "").strip() for t in case.tasks):
            reasons.append("همه Taskها بدون Description")

        very_short = [n for n in staff_notes if len((n.description or "").strip()) < 15]
        if rules["short_notes_majority"]["active"] and staff_notes and len(very_short) / len(staff_notes) > 0.5:
            reasons.append("بیش از نیمی از Noteها بسیار کوتاه (کمتر از ۱۵ کاراکتر)")

        text = _staff_text(case)
        action_recorded = bool(text.strip())
        result_recorded = _contains_any(text, RESULT_KEYWORDS)
        if rules["closed_without_result"]["active"] and action_recorded and not result_recorded and closed:
            reasons.append("Case بسته شده ولی نتیجه اقدام در متن ثبت نشده")

        if rules["low_confidence_task_links"]["active"] and len(case.task_links) >= rules["low_confidence_task_links"]["threshold"] and all(tl.confidence == "low" for tl in case.task_links):
            reasons.append("اتصال همه Taskها به این Case با اطمینان پایین (فقط تطبیق متنی) است")

        events = sorted([w for _, w, _ in case.all_events_sorted if w])
        if len(events) >= 2:
            gaps = [(events[i + 1] - events[i]).days for i in range(len(events) - 1)]
            if rules["long_event_gap"]["active"] and max(gaps) > rules["long_event_gap"]["threshold"]:
                reasons.append(f"فاصله زمانی غیرمنطقی ({max(gaps)} روز) بین دو رویداد متوالی")

        if reasons:
            flagged.append(SuspiciousCase(
                case_key=key, case_number=case.case_number, case_title=case.case_title, reasons=reasons,
            ))
    return flagged
