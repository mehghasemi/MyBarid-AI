from __future__ import annotations

from config.criteria_config import Criterion
from data.cleaner import CaseBundle
from analysis.timeline import build_timeline

SYSTEM_PROMPT_TEMPLATE = """تو یک «ارزیاب ارشد کیفیت خدمات پس از فروش و مستندسازی CRM» هستی.

اصول کار تو:
۱. فقط بر اساس اطلاعاتی که در ادامه (متن Noteها و Taskهای همین Case) داده می‌شود قضاوت کن.
۲. هرگز اطلاعاتی را که در Case وجود ندارد حدس نزن یا نسازی.
۳. اگر شواهد کافی برای یک معیار نبود، امتیاز را پایین بگذار و در evidence همین را صریحاً بنویس؛ عدد را دراماتیک نکن.
۴. بین «واقعیت ثبت‌شده» (Fact) و «برداشت خودت» (Interpretation) در نوشتن evidence تفاوت قائل شو.
۵. برای هر معیار، evidence باید مستقیماً به متن Note/Task ارجاع بدهد (نه یک جمله کلی).
۶. کیفیت اقدام را نسبت به مشکلی که مطرح شده بسنج، نه نسبت به یک استاندارد انتزاعی.
۷. نقاط قوت، نقاط ضعف و یک پیشنهاد عملی و مشخص (نه کلی‌گویی) استخراج کن.
۸. خروجی تو باید فقط یک شیء JSON معتبر باشد، بدون هیچ متن قبل یا بعد از آن.

معیارهایی که باید امتیاز بدهی (هرکدام بین ۰ تا ۱۰۰):
{criteria_list}

ساختار دقیق JSON خروجی:
{{
  "scores": {{ "<criterion_id>": <عدد ۰ تا ۱۰۰>, ... }},
  "evidence": {{ "<criterion_id>": "<دلیل کوتاه مبتنی بر متن Case>", ... }},
  "strengths": ["..."],
  "weaknesses": ["..."],
  "recommendations": ["..."],
  "confidence": "low" | "medium" | "high"
}}
"""


def build_system_prompt(criteria: list[Criterion]) -> str:
    lines = "\n".join(f"- {c.id}: {c.name_fa} — {c.description_fa}" for c in criteria)
    return SYSTEM_PROMPT_TEMPLATE.format(criteria_list=lines)


def build_case_prompt(case: CaseBundle) -> str:
    timeline = build_timeline(case)
    lines = [
        f"Case Number: {case.case_number or '(نامشخص)'}",
        f"عنوان: {case.case_title or '(نامشخص)'}",
        f"مشتری: {case.customer or '(نامشخص)'}",
        f"سرویس: {case.service or '(نامشخص)'}",
        f"وضعیت فعلی: {case.status or '(نامشخص)'} / {case.status_reason or ''}",
        "",
        "رویدادهای Case به‌ترتیب زمانی:",
    ]
    for ev in timeline:
        lines.append(f"[{ev['date']}] ({ev['type']} | {ev['role']} | {ev['author']}): {ev['text']}")
    if not timeline:
        lines.append("(هیچ رویداد دارای تاریخ معتبر ثبت نشده است.)")
    return "\n".join(lines)
