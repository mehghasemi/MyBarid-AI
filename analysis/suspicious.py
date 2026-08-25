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


def normalize_reason(reason: str) -> str:
    """Return the stable filter key/label for a suspicious-case reason.

    Details that vary per case, such as the measured number of days, must not
    create separate filter options for the same rule.
    """
    text = " ".join((reason or "").split())
    text = re.sub(r"\s*\(\s*\d+\s*روز\s*\)", "", text)
    text = re.sub(r"\s*\(\s*\d+\s*days?\s*\)", "", text, flags=re.IGNORECASE)
    return text.strip()


def find_suspicious_cases(cases: dict[str, CaseBundle]) -> list[SuspiciousCase]:
    flagged: list[SuspiciousCase] = []
    for key, case in cases.items():
        reasons: list[str] = []
        staff_notes = _staff_notes(case)

        if len(staff_notes) >= 3 and not case.tasks:
            reasons.append("Note های متعدد ولی بدون هیچ Task")

        if case.tasks and all(not (t.description or "").strip() for t in case.tasks):
            reasons.append("همه Taskها بدون Description")

        very_short = [n for n in staff_notes if len((n.description or "").strip()) < 15]
        if staff_notes and len(very_short) / len(staff_notes) > 0.5:
            reasons.append("بیش از نیمی از Noteها بسیار کوتاه (کمتر از ۱۵ کاراکتر)")

        text = _staff_text(case)
        action_recorded = bool(text.strip())
        result_recorded = _contains_any(text, RESULT_KEYWORDS)
        if action_recorded and not result_recorded and (case.status or "").casefold() in {"resolved", "closed"}:
            reasons.append("Case بسته شده ولی نتیجه اقدام در متن ثبت نشده")

        if len(case.task_links) >= 2 and all(tl.confidence == "low" for tl in case.task_links):
            reasons.append("اتصال همه Taskها به این Case با اطمینان پایین (فقط تطبیق متنی) است")

        events = sorted([w for _, w, _ in case.all_events_sorted if w])
        if len(events) >= 2:
            gaps = [(events[i + 1] - events[i]).days for i in range(len(events) - 1)]
            if max(gaps) > 60:
                reasons.append(f"فاصله زمانی غیرمنطقی ({max(gaps)} روز) بین دو رویداد متوالی")

        if reasons:
            flagged.append(SuspiciousCase(
                case_key=key, case_number=case.case_number, case_title=case.case_title, reasons=reasons,
            ))
    return flagged
