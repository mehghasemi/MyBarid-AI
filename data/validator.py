"""تبدیل سطرهای خام اکسل (بعد از Mapping) به رکوردهای کانونی + اعتبارسنجی.

هیچ رکوردی به‌خاطر «ناقص بودن» به‌طور کامل حذف نمی‌شود؛ فقط در آمار
«رکوردهای ناقص» شمرده می‌شود و لایه‌های تحلیل (Rule Engine) خودشان
تصمیم می‌گیرند چه امتیازی به آن بدهند (مثلاً Description خالی => امتیاز صفر).
استثنا: سطرهایی که هیچ تاریخ قابل‌پارس‌شدنی ندارند از تحلیلِ مبتنی بر
بازه‌ی زمانی کنار گذاشته می‌شوند، چون فیلتر دوره برایشان بی‌معناست؛ تعدادشان
هم در گزارش اعتبارسنجی گزارش می‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from data.loader import LoadedSheet
from data.mapper import (
    NOTES_FIELDS,
    TASKS_FIELDS,
    FieldSpec,
    MappingResult,
    detect_mapping,
)

_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
)


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # سریال تاریخ اکسل (fallback نادر؛ openpyxl معمولاً خودش تبدیل می‌کند)
        try:
            from datetime import timedelta

            return datetime(1899, 12, 30) + timedelta(days=float(value))
        except (ValueError, OverflowError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


@dataclass
class NoteRecord:
    note_id: str | None
    description: str
    case_number: str | None
    case_title: str | None
    customer: str | None
    owner: str | None
    service: str | None
    case_status: str | None
    case_status_reason: str | None
    case_created_on: datetime | None
    case_created_by: str | None
    note_date: datetime | None
    note_author: str | None
    assign_to: str | None
    incident_type: str | None
    case_description: str | None

    @property
    def case_key(self) -> str | None:
        return self.case_number or (f"عنوان::{self.case_title}" if self.case_title else None)

    @property
    def is_customer_authored(self) -> bool:
        author = (self.note_author or "").strip().casefold()
        return author in {"portal portal", "پرتال", "customer portal"}


@dataclass
class TaskRecord:
    task_id: str | None
    subject: str | None
    description: str | None
    case_number: str | None
    regarding: str | None
    created_by: str | None
    created_on: datetime | None
    actual_start: datetime | None
    due_date: datetime | None
    status_reason: str | None
    follow_up_needed: str | None
    next_follow_up: datetime | None
    work_type: str | None
    assign_to: str | None

    @property
    def case_key_hint(self) -> str | None:
        """کلید احتمالی برای اتصال به Case: اول شماره Case مستقیم، بعد Regarding."""
        return self.case_number or (f"عنوان::{self.regarding}" if self.regarding else None)


@dataclass
class ValidationSummary:
    file_name: str
    sheet_name: str
    total_rows: int
    usable_rows: int  # رکوردهایی که حداقل تاریخ معتبر دارند
    rows_without_date: int
    unique_cases: int
    incomplete_rows: int  # description خالی
    usable_columns: int
    total_columns: int
    mapping: dict[str, str | None]
    missing_required_labels: list[str]
    ambiguous: dict[str, list[str]]
    unmatched_headers: list[str]
    warnings: list[str] = field(default_factory=list)


def _get(row: dict[str, Any], mapping: dict[str, str | None], field_name: str) -> Any:
    header = mapping.get(field_name)
    if header is None:
        return None
    value = row.get(header)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def normalize_notes(loaded: LoadedSheet) -> tuple[list[NoteRecord], MappingResult, ValidationSummary]:
    mr = detect_mapping(loaded.headers, NOTES_FIELDS)
    records: list[NoteRecord] = []
    rows_without_date = 0
    incomplete = 0
    case_keys: set[str] = set()

    for row in loaded.rows:
        note_date = parse_datetime(_get(row, mr.mapping, "note_date"))
        if note_date is None:
            rows_without_date += 1
        description = _get(row, mr.mapping, "description") or ""
        if not description.strip():
            incomplete += 1
        rec = NoteRecord(
            note_id=_get(row, mr.mapping, "note_id"),
            description=description,
            case_number=_get(row, mr.mapping, "case_number"),
            case_title=_get(row, mr.mapping, "case_title"),
            customer=_get(row, mr.mapping, "customer"),
            owner=_get(row, mr.mapping, "owner"),
            service=_get(row, mr.mapping, "service"),
            case_status=_get(row, mr.mapping, "case_status"),
            case_status_reason=_get(row, mr.mapping, "case_status_reason"),
            case_created_on=parse_datetime(_get(row, mr.mapping, "case_created_on")),
            case_created_by=_get(row, mr.mapping, "case_created_by"),
            note_date=note_date,
            note_author=_get(row, mr.mapping, "note_author"),
            assign_to=_get(row, mr.mapping, "assign_to"),
            incident_type=_get(row, mr.mapping, "incident_type"),
            case_description=_get(row, mr.mapping, "case_description"),
        )
        if rec.case_key:
            case_keys.add(rec.case_key)
        records.append(rec)

    warnings = []
    if not mr.mapping.get("case_number"):
        warnings.append(
            "ستون «شماره Case» در فایل Notes پیدا نشد؛ گروه‌بندی موقتاً بر اساس «عنوان Case» انجام می‌شود که ممکن است دقیق نباشد."
        )
    if mr.ambiguous:
        for fname, cands in mr.ambiguous.items():
            label = next((s.label_fa for s in NOTES_FIELDS if s.name == fname), fname)
            warnings.append(
                f"برای فیلد «{label}» چند ستون مشابه پیدا شد ({', '.join(cands)})؛ ستون «{cands[0]}» انتخاب شد. در صورت نیاز می‌توانید در تنظیمات Mapping را دستی اصلاح کنید."
            )

    summary = ValidationSummary(
        file_name=loaded.file_name,
        sheet_name=loaded.sheet_name,
        total_rows=len(loaded.rows),
        usable_rows=len(loaded.rows) - rows_without_date,
        rows_without_date=rows_without_date,
        unique_cases=len(case_keys),
        incomplete_rows=incomplete,
        usable_columns=sum(1 for v in mr.mapping.values() if v),
        total_columns=len(loaded.headers),
        mapping=mr.mapping,
        missing_required_labels=[s.label_fa for s in mr.missing_required],
        ambiguous=mr.ambiguous,
        unmatched_headers=mr.unmatched_headers,
        warnings=warnings,
    )
    return records, mr, summary


def normalize_tasks(loaded: LoadedSheet) -> tuple[list[TaskRecord], MappingResult, ValidationSummary]:
    mr = detect_mapping(loaded.headers, TASKS_FIELDS)
    records: list[TaskRecord] = []
    rows_without_date = 0
    incomplete = 0
    case_keys: set[str] = set()

    for row in loaded.rows:
        created_on = parse_datetime(_get(row, mr.mapping, "created_on"))
        if created_on is None:
            rows_without_date += 1
        description = _get(row, mr.mapping, "description")
        if not description and not _get(row, mr.mapping, "subject"):
            incomplete += 1
        rec = TaskRecord(
            task_id=_get(row, mr.mapping, "task_id"),
            subject=_get(row, mr.mapping, "subject"),
            description=description,
            case_number=_get(row, mr.mapping, "case_number"),
            regarding=_get(row, mr.mapping, "regarding"),
            created_by=_get(row, mr.mapping, "created_by"),
            created_on=created_on,
            actual_start=parse_datetime(_get(row, mr.mapping, "actual_start")),
            due_date=parse_datetime(_get(row, mr.mapping, "due_date")),
            status_reason=_get(row, mr.mapping, "status_reason"),
            follow_up_needed=_get(row, mr.mapping, "follow_up_needed"),
            next_follow_up=parse_datetime(_get(row, mr.mapping, "next_follow_up")),
            work_type=_get(row, mr.mapping, "work_type"),
            assign_to=_get(row, mr.mapping, "assign_to"),
        )
        if rec.case_key_hint:
            case_keys.add(rec.case_key_hint)
        records.append(rec)

    warnings = []
    if not mr.mapping.get("case_number"):
        warnings.append(
            "ستون «شماره Case» در فایل Tasks پیدا نشد؛ اتصال Task به Case بر اساس تطبیق متنی «Regarding» با «عنوان Case» در فایل Notes انجام می‌شود (Best-Effort، همراه با درجه اطمینان)."
        )
    if mr.ambiguous:
        for fname, cands in mr.ambiguous.items():
            label = next((s.label_fa for s in TASKS_FIELDS if s.name == fname), fname)
            warnings.append(
                f"برای فیلد «{label}» چند ستون مشابه پیدا شد ({', '.join(cands)})؛ ستون «{cands[0]}» انتخاب شد."
            )

    summary = ValidationSummary(
        file_name=loaded.file_name,
        sheet_name=loaded.sheet_name,
        total_rows=len(loaded.rows),
        usable_rows=len(loaded.rows) - rows_without_date,
        rows_without_date=rows_without_date,
        unique_cases=len(case_keys),
        incomplete_rows=incomplete,
        usable_columns=sum(1 for v in mr.mapping.values() if v),
        total_columns=len(loaded.headers),
        mapping=mr.mapping,
        missing_required_labels=[s.label_fa for s in mr.missing_required],
        ambiguous=mr.ambiguous,
        unmatched_headers=mr.unmatched_headers,
        warnings=warnings,
    )
    return records, mr, summary
