"""شناسایی و Mapping ستون‌های فایل اکسل به فیلدهای کانونی برنامه.

اصل طراحی: به هیچ نام ستونی به‌صورت Hard-Code تکیه نمی‌کنیم. برای هر فیلد
کانونی، فهرستی از نام‌های محتمل (به ترتیب اولویت) تعریف شده و اولین
تطبیق دقیق (case-insensitive) انتخاب می‌شود. اگر هیچ‌کدام دقیق نبود، یک
تلاش برای تطبیق تقریبی (substring) انجام می‌شود تا اختلاف‌های جزئی (فاصله،
پرانتز و ...) هم پوشش داده شوند.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FieldSpec:
    name: str  # نام کانونی داخلی (انگلیسی، برای کد)
    label_fa: str  # برچسب فارسی برای نمایش به کاربر
    aliases: list[str]  # به ترتیب اولویت
    required: bool = False
    exact_only: bool = False  # اگر True، فقط تطبیق دقیق مجاز است (برای جلوگیری از اشتباه‌گرفتن با فیلدهای «(Regarding) (Case)»)


NOTES_FIELDS: list[FieldSpec] = [
    FieldSpec("note_id", "شناسه Note", ["(Do Not Modify) Note", "Note", "Annotation Id", "Activity Id"]),
    FieldSpec("description", "شرح Note (Description)", ["Description"], required=True, exact_only=True),
    FieldSpec("case_number", "شماره Case", [
        "Case Number (Regarding) (Case)", "Case Number", "Ticket Number", "شماره کیس", "شماره کیس (Regarding)",
    ]),
    FieldSpec("case_title", "عنوان Case", ["Case Title (Regarding) (Case)", "Case Title", "عنوان کیس"]),
    FieldSpec("customer", "مشتری", ["Customer (Regarding) (Case)", "Customer", "مشتری"]),
    FieldSpec("owner", "Owner", ["Owner (Regarding) (Case)", "Owner"]),
    FieldSpec("service", "سرویس", ["Service (Regarding) (Case)", "Case Service (Regarding) (Case)", "Service"]),
    FieldSpec("case_status", "وضعیت Case", ["Status (Regarding) (Case)", "Status"]),
    FieldSpec("case_status_reason", "دلیل وضعیت Case", ["Status Reason (Regarding) (Case)", "Status Reason"]),
    FieldSpec("case_created_on", "تاریخ ایجاد Case", ["Created On (Regarding) (Case)", "Case Created On"]),
    FieldSpec("case_created_by", "ایجادکننده Case", ["Created By (Regarding) (Case)", "Case Created By"]),
    # تاریخ خودِ Note: در اکسپورت‌های Dynamics معمولاً «Created On» مستقل برای Note وجود ندارد
    # و «Modified On» (یا ستون Do Not Modify) عملاً معادل زمان ثبت است.
    FieldSpec("note_date", "تاریخ ثبت Note", [
        "(Do Not Modify) Modified On", "Created On", "Modified On",
    ], required=True, exact_only=True),
    FieldSpec("note_author", "ثبت‌کننده Note", ["Modified By", "Created By"], exact_only=True),
    FieldSpec("assign_to", "واگذارشده به", ["Assign To (Regarding) (Case)", "Assign To"]),
    FieldSpec("incident_type", "نوع Incident", ["Incident Type (Regarding) (Case)", "Incident Type"]),
    FieldSpec("case_description", "شرح Case", ["Description (Regarding) (Case)"], exact_only=True),
]

TASKS_FIELDS: list[FieldSpec] = [
    FieldSpec("task_id", "شناسه Task", ["(Do Not Modify) Task", "Task", "Activity Id"]),
    FieldSpec("subject", "عنوان Task (Subject)", ["Subject"], exact_only=True),
    FieldSpec("description", "شرح Task (Description)", ["Description"], exact_only=True),
    # اگر شماره Case مستقیم در فایل Task موجود باشد (پیشنهاد ما به کاربر)، اولویت با آن است؛
    # در غیر این صورت به Regarding (که معمولاً معادل عنوان Case است) برای تطبیق متنی رجوع می‌شود.
    FieldSpec("case_number", "شماره Case", [
        "Case Number (Regarding) (Case)", "Case Number", "Ticket Number", "شماره کیس",
    ]),
    FieldSpec("regarding", "Regarding", ["Regarding"], required=True, exact_only=True),
    FieldSpec("created_by", "ایجادکننده Task", ["Created By"], exact_only=True),
    FieldSpec("created_on", "تاریخ ایجاد Task", ["Created On"], required=True, exact_only=True),
    FieldSpec("actual_start", "شروع واقعی", ["Actual Start"]),
    FieldSpec("due_date", "سررسید", ["Due Date", "Scheduled End"]),
    FieldSpec("status_reason", "وضعیت Task", ["Status Reason (Regarding) (Case)", "Status Reason", "Status"]),
    FieldSpec("follow_up_needed", "نیاز به پیگیری", ["Follow Up Needed"]),
    FieldSpec("next_follow_up", "پیگیری بعدی", ["Next Follow Up"]),
    FieldSpec("work_type", "نوع کار هلپ‌دسک", ["Helpdesk Work Type", "Work Type"]),
    FieldSpec("assign_to", "واگذارشده به", ["Assign To (Regarding) (Case)", "Assign To"]),
]


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


@dataclass
class MappingResult:
    mapping: dict[str, str | None]  # canonical -> header اصلی (یا None اگر پیدا نشد)
    missing_required: list[FieldSpec]
    unmatched_headers: list[str]
    ambiguous: dict[str, list[str]]  # فیلدهایی که چند کاندید نزدیک داشتند


def detect_mapping(headers: list[str], specs: list[FieldSpec]) -> MappingResult:
    norm_headers = {h: _normalize(h) for h in headers}
    used_headers: set[str] = set()
    mapping: dict[str, str | None] = {}
    ambiguous: dict[str, list[str]] = {}

    for spec in specs:
        matched: str | None = None
        # ۱) تطبیق دقیق بر اساس ترتیب alias
        for alias in spec.aliases:
            alias_norm = _normalize(alias)
            for h in headers:
                if h in used_headers:
                    continue
                if norm_headers[h] == alias_norm:
                    matched = h
                    break
            if matched:
                break

        # ۲) تطبیق تقریبی (فقط اگر exact_only نباشد)
        candidates: list[str] = []
        if not matched and not spec.exact_only:
            for alias in spec.aliases:
                alias_norm = _normalize(alias)
                for h in headers:
                    if h in used_headers:
                        continue
                    hn = norm_headers[h]
                    # فقط اگر عبارتِ Alias به‌طور کامل داخل نام ستون باشد (نه برعکس)؛
                    # جهت معکوس (نام ستون کوتاه داخل Alias بلند) باعث تطبیق‌های اشتباه می‌شود
                    # (مثلاً ستون «Regarding» داخل Alias «Case Number (Regarding) (Case)»).
                    if alias_norm and alias_norm in hn:
                        candidates.append(h)
            candidates = list(dict.fromkeys(candidates))  # حفظ ترتیب، حذف تکراری
            if len(candidates) == 1:
                matched = candidates[0]
            elif len(candidates) > 1:
                ambiguous[spec.name] = candidates
                matched = candidates[0]  # بهترین حدس، ولی به کاربر اطلاع می‌دهیم

        mapping[spec.name] = matched
        if matched:
            used_headers.add(matched)

    missing_required = [s for s in specs if s.required and not mapping.get(s.name)]
    unmatched_headers = [h for h in headers if h not in used_headers]

    return MappingResult(
        mapping=mapping,
        missing_required=missing_required,
        unmatched_headers=unmatched_headers,
        ambiguous=ambiguous,
    )
