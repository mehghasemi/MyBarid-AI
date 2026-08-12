"""شاخص سلامت داده CRM: مستقل از عملکرد کارشناسان محاسبه می‌شود.

خروجی هر Check یک عدد بین ۰ تا ۱۰۰ (بالاتر = سالم‌تر) به همراه تعداد
رکورد مشکل‌دار است. شاخص نهایی، میانگین ساده این Checkها است (چون همه از
یک جنس‌اند: درصد سلامت).
"""
from __future__ import annotations

from dataclasses import dataclass

from data.cleaner import CaseBundle, detect_duplicate_notes, detect_duplicate_tasks
from data.validator import NoteRecord, TaskRecord

MAX_REASONABLE_GAP_DAYS = 180  # فاصله بیش از این بین دو رویداد متوالی، غیرمنطقی تلقی می‌شود


@dataclass
class HealthCheckResult:
    id: str
    name_fa: str
    healthy_score: float  # 0..100
    issue_count: int
    detail_fa: str


def compute_data_health(
    notes: list[NoteRecord],
    tasks: list[TaskRecord],
    cases: dict[str, CaseBundle],
    unmatched_tasks: list[TaskRecord],
) -> tuple[list[HealthCheckResult], float]:
    results: list[HealthCheckResult] = []

    # Note بدون Description
    empty_notes = sum(1 for n in notes if not (n.description or "").strip())
    results.append(HealthCheckResult(
        "notes_without_description", "Note بدون Description",
        _pct(len(notes) - empty_notes, len(notes)), empty_notes,
        f"{empty_notes} از {len(notes)} Note بدون متن هستند." if notes else "داده‌ای برای بررسی وجود ندارد.",
    ))

    # Task بدون Description
    empty_tasks = sum(1 for t in tasks if not (t.description or "").strip())
    results.append(HealthCheckResult(
        "tasks_without_description", "Task بدون Description",
        _pct(len(tasks) - empty_tasks, len(tasks)), empty_tasks,
        f"{empty_tasks} از {len(tasks)} Task بدون متن هستند." if tasks else "Task ای برای بررسی وجود ندارد.",
    ))

    # Case بدون Note
    cases_no_note = sum(1 for c in cases.values() if not c.notes)
    results.append(HealthCheckResult(
        "cases_without_note", "Case بدون Note",
        _pct(len(cases) - cases_no_note, len(cases)), cases_no_note,
        f"{cases_no_note} از {len(cases)} Case هیچ Note ای ندارند (فقط از طریق Task شناسایی شده‌اند).",
    ))

    # Case بدون Task
    cases_no_task = sum(1 for c in cases.values() if not c.tasks)
    results.append(HealthCheckResult(
        "cases_without_task", "Case بدون Task",
        _pct(len(cases) - cases_no_task, len(cases)), cases_no_task,
        f"{cases_no_task} از {len(cases)} Case هیچ Task ای ندارند.",
    ))

    # تکراری‌ها
    dup_notes = detect_duplicate_notes(notes)
    results.append(HealthCheckResult(
        "duplicate_notes", "Note تکراری",
        _pct(len(notes) - dup_notes, len(notes)), dup_notes,
        f"{dup_notes} Note تکراری شناسایی شد." if notes else "داده‌ای وجود ندارد.",
    ))
    dup_tasks = detect_duplicate_tasks(tasks)
    results.append(HealthCheckResult(
        "duplicate_tasks", "Task تکراری",
        _pct(len(tasks) - dup_tasks, len(tasks)), dup_tasks,
        f"{dup_tasks} Task تکراری شناسایی شد." if tasks else "داده‌ای وجود ندارد.",
    ))

    # Task بدون اتصال به هیچ Case
    results.append(HealthCheckResult(
        "unmatched_tasks", "Task قابل‌اتصال به هیچ Case‌ای نیست",
        _pct(len(tasks) - len(unmatched_tasks), len(tasks)), len(unmatched_tasks),
        f"{len(unmatched_tasks)} از {len(tasks)} Task به هیچ Case ای (نه با شماره، نه با تطبیق عنوان) متصل نشدند."
        if tasks else "داده‌ای وجود ندارد.",
    ))

    # Timestamp غیرمنطقی
    bad_gap_cases = 0
    for c in cases.values():
        events = sorted([w for _, w, _ in c.all_events_sorted if w])
        if len(events) < 2:
            continue
        max_gap = max((events[i + 1] - events[i]).days for i in range(len(events) - 1))
        if max_gap > MAX_REASONABLE_GAP_DAYS:
            bad_gap_cases += 1
    results.append(HealthCheckResult(
        "unreasonable_timestamps", "Timestamp غیرمنطقی",
        _pct(len(cases) - bad_gap_cases, len(cases)), bad_gap_cases,
        f"{bad_gap_cases} Case دارای فاصله زمانی بیش از {MAX_REASONABLE_GAP_DAYS} روز بین دو رویداد متوالی هستند.",
    ))

    overall = round(sum(r.healthy_score for r in results) / len(results), 1) if results else 0.0
    return results, overall


def _pct(healthy: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return round(max(0, healthy) / total * 100, 1)
