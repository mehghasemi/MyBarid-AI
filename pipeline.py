from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ai.analyzer import analyze_cases
from ai.providers import AISettings
from analysis.comparison import compare_periods
from analysis.data_quality import compute_data_health
from analysis.experts import aggregate_experts, primary_expert, rank_experts
from analysis.scoring import CaseScoreBreakdown, score_case
from analysis.suspicious import find_suspicious_cases
from config.criteria_config import CriteriaConfig
from data.cleaner import CaseBundle, build_cases, build_task_pseudo_cases
from data.loader import ExcelLoadError, load_excel
from data.validator import NoteRecord, TaskRecord, ValidationSummary, normalize_notes, normalize_tasks


@dataclass
class Dataset:
    notes: list[NoteRecord]
    tasks: list[TaskRecord]
    cases: dict[str, CaseBundle]
    unmatched_tasks: list[TaskRecord]
    notes_summary: ValidationSummary
    tasks_summary: ValidationSummary


def load_dataset(notes_path: str, tasks_path: str, max_rows: int | None = None) -> Dataset:
    notes_sheet = load_excel(notes_path, max_rows=max_rows)
    tasks_sheet = load_excel(tasks_path, max_rows=max_rows)

    notes, notes_mr, notes_summary = normalize_notes(notes_sheet)
    tasks, tasks_mr, tasks_summary = normalize_tasks(tasks_sheet)

    if notes_mr.missing_required:
        labels = "، ".join(notes_summary.missing_required_labels)
        raise ExcelLoadError(f"در فایل Notes، ستون‌های ضروری زیر پیدا نشد: {labels}")
    if tasks_mr.missing_required:
        labels = "، ".join(tasks_summary.missing_required_labels)
        raise ExcelLoadError(f"در فایل Tasks، ستون‌های ضروری زیر پیدا نشد: {labels}")

    cases, unmatched = build_cases(notes, tasks)
    return Dataset(
        notes=notes, tasks=tasks, cases=cases, unmatched_tasks=unmatched,
        notes_summary=notes_summary, tasks_summary=tasks_summary,
    )


def filter_period(
    dataset: Dataset, start: datetime, end: datetime, expert_filter: set[str] | None = None,
) -> tuple[dict[str, CaseBundle], list]:
    notes_in = [n for n in dataset.notes if n.note_date and start <= n.note_date <= end]
    tasks_in = [t for t in dataset.tasks if t.created_on and start <= t.created_on <= end]
    cases, unmatched = build_cases(notes_in, tasks_in)
    # تکمیل فیلدهای توصیفی (عنوان/مشتری/...) از دیتاست کامل، در صورت خالی بودن در بازه فیلترشده
    for key, bundle in cases.items():
        full = dataset.cases.get(key)
        if not full:
            continue
        bundle.case_title = bundle.case_title or full.case_title
        bundle.customer = bundle.customer or full.customer
        bundle.owner = bundle.owner or full.owner
        bundle.service = bundle.service or full.service
        bundle.scenario = bundle.scenario or full.scenario
        bundle.case_description = bundle.case_description or full.case_description
    if expert_filter:
        cases = {k: v for k, v in cases.items() if primary_expert(v) in expert_filter}
    return cases, unmatched


def filter_period_task_mode(
    dataset: Dataset, start: datetime, end: datetime, expert_filter: set[str] | None = None,
) -> dict[str, CaseBundle]:
    """معادل filter_period ولی برای کارشناسان پشتیبانی فنی: واحد بررسی Task
    است، نه Case. هر Task مستقیماً به کارشناس ثبت‌کننده‌اش (Created By)
    نسبت داده می‌شود."""
    tasks_in = [t for t in dataset.tasks if t.created_on and start <= t.created_on <= end]
    if expert_filter:
        tasks_in = [t for t in tasks_in if (t.created_by or "") in expert_filter]
    return build_task_pseudo_cases(tasks_in)


def score_all(cases: dict[str, CaseBundle], config: CriteriaConfig,
              ai_results: dict[str, dict] | None = None, unit: str = "case") -> dict[str, CaseScoreBreakdown]:
    ai_results = ai_results or {}
    return {key: score_case(case, config, ai_results.get(key), unit=unit) for key, case in cases.items()}


@dataclass
class PeriodResult:
    cases: dict[str, CaseBundle]
    scores: dict[str, CaseScoreBreakdown]
    ai_errors: dict[str, str]


def run_period(
    dataset: Dataset, config: CriteriaConfig, start: datetime, end: datetime,
    ai_settings: AISettings, progress_cb: Callable[[int, int, str], None] | None = None,
    expert_filter: set[str] | None = None, unit: str = "case", force_ai: bool = False,
) -> PeriodResult:
    if unit == "task":
        cases = filter_period_task_mode(dataset, start, end, expert_filter)
    else:
        cases, _ = filter_period(dataset, start, end, expert_filter)
    # در حالت Task، AI فعلاً اجرا نمی‌شود (معیارهای Task مستقل همگی Rule-Based تعریف شده‌اند)
    ai_results, ai_errors = ({}, {}) if unit == "task" else analyze_cases(
        cases, config, ai_settings, progress_cb, force=force_ai)
    scores = score_all(cases, config, ai_results, unit=unit)
    return PeriodResult(cases=cases, scores=scores, ai_errors=ai_errors)


def run_full_analysis(
    dataset: Dataset, config: CriteriaConfig,
    period1: tuple[datetime, datetime], period2: tuple[datetime, datetime],
    ai_settings: AISettings, progress_cb: Callable[[str, int, int], None] | None = None,
    expert_filter: set[str] | None = None, unit: str = "case", force_ai: bool = False,
) -> dict:
    def cb_wrap(label):
        def _cb(i, n, key):
            if progress_cb:
                progress_cb(label, i, n)
        return _cb

    r1 = run_period(dataset, config, period1[0], period1[1], ai_settings, cb_wrap("دوره اول"), expert_filter, unit, force_ai)
    r2 = run_period(dataset, config, period2[0], period2[1], ai_settings, cb_wrap("دوره دوم"), expert_filter, unit, force_ai)

    comparison = compare_periods(r1.cases, r1.scores, r2.cases, r2.scores, config)

    experts_p1 = aggregate_experts(r1.cases, r1.scores)
    experts_p2 = aggregate_experts(r2.cases, r2.scores)
    ranking = rank_experts(experts_p1, experts_p2)

    health_checks, health_index = compute_data_health(
        dataset.notes, dataset.tasks, dataset.cases, dataset.unmatched_tasks
    )

    if unit == "task":
        all_tasks = dataset.tasks
        if expert_filter:
            all_tasks = [t for t in all_tasks if (t.created_by or "") in expert_filter]
        suspicious_pool = build_task_pseudo_cases(all_tasks)
    else:
        suspicious_pool = dataset.cases
        if expert_filter:
            suspicious_pool = {k: v for k, v in dataset.cases.items() if primary_expert(v) in expert_filter}
    suspicious = find_suspicious_cases(suspicious_pool)

    return {
        "mode": "comparison",
        "period1": r1,
        "period2": r2,
        "comparison": comparison,
        "experts_p1": experts_p1,
        "experts_p2": experts_p2,
        "ranking": ranking,
        "data_health_checks": health_checks,
        "data_health_index": health_index,
        "suspicious": suspicious,
        "unit": unit,
    }


def run_general_analysis(
    dataset: Dataset, config: CriteriaConfig, ai_settings: AISettings,
    progress_cb: Callable[[str, int, int], None] | None = None,
    expert_filter: set[str] | None = None, unit: str = "case", force_ai: bool = False,
) -> dict:
    """Analyze the current dataset as one independent population."""
    def progress(i, n, key):
        if progress_cb:
            progress_cb("تحلیل کلی", i, n)

    if unit == "task":
        tasks = dataset.tasks
        if expert_filter:
            tasks = [t for t in tasks if (t.created_by or "") in expert_filter]
        cases = build_task_pseudo_cases(tasks)
    else:
        cases = dict(dataset.cases)
        if expert_filter:
            cases = {k: v for k, v in cases.items() if primary_expert(v) in expert_filter}
    ai_results, ai_errors = ({}, {}) if unit == "task" else analyze_cases(
        cases, config, ai_settings, progress, force=force_ai
    )
    scores = score_all(cases, config, ai_results, unit=unit)
    general = PeriodResult(cases=cases, scores=scores, ai_errors=ai_errors)

    def avg(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 1) if values else None

    categories = [
        {"id": cat.id, "name_fa": cat.name_fa,
         "value": avg([b.category_scores.get(cat.id) for b in scores.values()])}
        for cat in config.categories
    ]
    criteria = [
        {"id": crit.id, "name_fa": crit.name_fa,
         "value": avg([cs.score for b in scores.values() for cs in b.criterion_scores
                       if cs.criterion_id == crit.id])}
        for _, crit in config.active_criteria()
    ]
    overall = avg([b.final_score for b in scores.values()])
    experts = aggregate_experts(cases, scores)
    ranking = [{
        "expert": expert, "score": stats.avg_final, "cases": stats.case_count,
        "status": "تحلیل کلی",
    } for expert, stats in experts.items()]
    ranking.sort(key=lambda row: (row["score"] is None, -(row["score"] or 0)))
    health_checks, health_index = compute_data_health(
        dataset.notes, dataset.tasks, dataset.cases, dataset.unmatched_tasks
    )
    suspicious_pool = (
        build_task_pseudo_cases([
            t for t in dataset.tasks
            if not expert_filter or (t.created_by or "") in expert_filter
        ]) if unit == "task" else cases
    )
    return {
        "mode": "general", "general": general, "general_score": overall,
        "general_categories": categories, "general_criteria": criteria,
        "general_narrative": (
            f"امتیاز کلی برای {len(cases)} مورد: "
            f"{overall if overall is not None else 'قابل محاسبه نیست'}."
        ),
        "experts_general": experts, "ranking": ranking,
        "data_health_checks": health_checks, "data_health_index": health_index,
        "suspicious": find_suspicious_cases(suspicious_pool), "unit": unit,
    }
