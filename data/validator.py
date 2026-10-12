"""CRM normalized records, date conversion and source validation summary.

Module path is retained for existing serialized snapshots. No Workbook ingestion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo:
                from datetime import timezone
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
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
    scenario: str | None
    case_id: str | None = None
    created_on: datetime | None = None
    modified_on: datetime | None = None
    modified_by: str | None = None
    is_customer_response: bool | None = None

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
    case_id: str | None = None
    actual_end: datetime | None = None
    state_code: str | None = None
    owner: str | None = None
    modified_by: str | None = None

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
