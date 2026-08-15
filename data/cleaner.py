"""ساخت «باندل Case»: گروه‌بندی Noteها بر اساس Case و اتصال Taskها به آن.

استراتژی اتصال Task به Case (به ترتیب اولویت):
  ۱) اگر ستون «شماره Case» مستقیماً در فایل Task موجود باشد -> اتصال دقیق (High).
  ۲) در غیر این صورت، مقدار «Regarding» با «عنوان Case»‌های شناخته‌شده از فایل
     Notes به‌صورت نرمال‌شده مقایسه می‌شود:
       - تطبیق دقیق و یکتا -> Medium confidence.
       - تطبیق دقیق ولی به چند Case مختلف (عنوان تکراری) -> Low confidence،
         نزدیک‌ترین Case از نظر زمانی (created_on Case نزدیک به created_on Task) انتخاب می‌شود.
       - بدون تطبیق -> Unmatched (در گزارش «Cases نیازمند بررسی» و آمار کیفیت داده لحاظ می‌شود).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from data.validator import NoteRecord, TaskRecord

LinkConfidence = str  # "high" | "medium" | "low" | "unmatched"


@dataclass
class TaskLink:
    task: TaskRecord
    confidence: LinkConfidence


@dataclass
class CaseBundle:
    case_key: str
    case_number: str | None
    case_title: str | None
    customer: str | None
    owner: str | None
    service: str | None
    status: str | None
    status_reason: str | None
    created_on: datetime | None
    notes: list[NoteRecord] = field(default_factory=list)
    task_links: list[TaskLink] = field(default_factory=list)

    @property
    def tasks(self) -> list[TaskRecord]:
        return [tl.task for tl in self.task_links]

    @property
    def all_events_sorted(self):
        events = []
        for n in self.notes:
            if n.note_date:
                events.append(("note", n.note_date, n))
        for tl in self.task_links:
            t = tl.task
            when = t.created_on or t.actual_start
            if when:
                events.append(("task", when, t))
        events.sort(key=lambda e: e[1])
        return events


def _normalize_title(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().casefold().split())


def build_cases(
    notes: list[NoteRecord], tasks: list[TaskRecord]
) -> tuple[dict[str, CaseBundle], list[TaskRecord]]:
    cases: dict[str, CaseBundle] = {}
    title_to_keys: dict[str, list[str]] = {}

    for n in notes:
        key = n.case_key
        if not key:
            continue
        if key not in cases:
            cases[key] = CaseBundle(
                case_key=key,
                case_number=n.case_number,
                case_title=n.case_title,
                customer=n.customer,
                owner=n.owner,
                service=n.service,
                status=n.case_status,
                status_reason=n.case_status_reason,
                created_on=n.case_created_on,
            )
        else:
            bundle = cases[key]
            # تکمیل فیلدهای خالی از رکوردهای بعدی همان Case
            bundle.customer = bundle.customer or n.customer
            bundle.owner = bundle.owner or n.owner
            bundle.service = bundle.service or n.service
            bundle.status = n.case_status or bundle.status
            bundle.status_reason = n.case_status_reason or bundle.status_reason
            bundle.created_on = bundle.created_on or n.case_created_on
        cases[key].notes.append(n)
        title_norm = _normalize_title(n.case_title)
        if title_norm:
            title_to_keys.setdefault(title_norm, [])
            if key not in title_to_keys[title_norm]:
                title_to_keys[title_norm].append(key)

    unmatched_tasks: list[TaskRecord] = []

    for t in tasks:
        # ۱) اتصال دقیق با شماره Case
        if t.case_number and t.case_number in cases:
            cases[t.case_number].task_links.append(TaskLink(task=t, confidence="high"))
            continue
        if t.case_number:
            # شماره Case در فایل Task هست ولی در Notes پیدا نشد -> Case بدون Note
            key = t.case_number
            if key not in cases:
                cases[key] = CaseBundle(
                    case_key=key, case_number=t.case_number, case_title=t.regarding,
                    customer=None, owner=None, service=None, status=None,
                    status_reason=None, created_on=None,
                )
            cases[key].task_links.append(TaskLink(task=t, confidence="high"))
            continue

        # ۲) Fallback: تطبیق متنی Regarding با عنوان Case
        title_norm = _normalize_title(t.regarding)
        candidate_keys = title_to_keys.get(title_norm, [])
        if len(candidate_keys) == 1:
            cases[candidate_keys[0]].task_links.append(TaskLink(task=t, confidence="medium"))
        elif len(candidate_keys) > 1:
            best_key = _closest_by_time(candidate_keys, cases, t)
            cases[best_key].task_links.append(TaskLink(task=t, confidence="low"))
        else:
            unmatched_tasks.append(t)

    return cases, unmatched_tasks


def _closest_by_time(keys: list[str], cases: dict[str, CaseBundle], task: TaskRecord) -> str:
    ref = task.created_on or task.actual_start
    if not ref:
        return keys[0]
    best_key, best_diff = keys[0], None
    for k in keys:
        c = cases[k]
        anchor = c.created_on or (c.notes[0].note_date if c.notes else None)
        if not anchor:
            continue
        diff = abs((anchor - ref).total_seconds())
        if best_diff is None or diff < best_diff:
            best_key, best_diff = k, diff
    return best_key


def detect_duplicate_notes(notes: list[NoteRecord]) -> int:
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for n in notes:
        if not n.case_key or not n.description:
            continue
        sig = (n.case_key, " ".join(n.description.split()).casefold()[:300])
        if sig in seen:
            duplicates += 1
        else:
            seen.add(sig)
    return duplicates


def detect_duplicate_tasks(tasks: list[TaskRecord]) -> int:
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for t in tasks:
        key = t.case_number or t.regarding or ""
        text = " ".join((t.description or t.subject or "").split()).casefold()[:300]
        if not text:
            continue
        sig = (key, text)
        if sig in seen:
            duplicates += 1
        else:
            seen.add(sig)
    return duplicates


def build_task_pseudo_cases(tasks: list[TaskRecord]) -> dict[str, CaseBundle]:
    """برای ارزیابی مبتنی بر Task (کارشناسان پشتیبانی فنی): هر Task به‌عنوان
    یک «شبه‌Case» تک‌عضوی نمایش داده می‌شود تا بتوان از همان زیرساخت Scoring/
    Comparison/Ranking موجود (که روی CaseBundle کار می‌کند) بدون تغییر
    معماری اصلی استفاده کرد. صاحب این شبه‌Case مستقیماً «Created By» خودِ
    Task است، نه استنتاج از حجم Note (که برای Task اصلاً وجود ندارد)."""
    cases: dict[str, CaseBundle] = {}
    for i, t in enumerate(tasks):
        key = t.task_id or f"task::{i}"
        cases[key] = CaseBundle(
            case_key=key,
            case_number=t.task_id,
            case_title=t.subject or t.regarding,
            customer=None,
            owner=t.created_by,
            service=None,
            status=t.status_reason,
            status_reason=t.status_reason,
            created_on=t.created_on,
            notes=[],
            task_links=[TaskLink(task=t, confidence="high")],
        )
    return cases
