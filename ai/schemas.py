from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict | None:
    """تلاش برای استخراج و Parse یک شیء JSON از متن پاسخ مدل، حتی اگر مدل
    متن اضافی (مثل ```json ... ```) دور آن گذاشته باشد."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def validate_case_analysis(payload: dict, expected_criteria: list[str]) -> tuple[bool, list[str]]:
    """بررسی می‌کند خروجی شامل امتیاز عددی برای معیارهای موردانتظار هست یا نه.
    خروجی: (is_valid, missing_or_invalid_fields)."""
    problems: list[str] = []
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        return False, ["فیلد scores در خروجی JSON یافت نشد."]
    for cid in expected_criteria:
        val = scores.get(cid)
        if not isinstance(val, (int, float)) or not (0 <= val <= 100):
            problems.append(cid)
    if not isinstance(payload.get("evidence"), dict):
        problems.append("evidence")
    return (len(problems) == 0), problems
