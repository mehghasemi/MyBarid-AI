from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable
from types import SimpleNamespace

from ai.analyzer import analyze_cases
from ai.providers import AISettings
from analysis.data_quality import compute_data_health
from analysis.experts import aggregate_experts, primary_expert
from analysis.scoring import CaseScoreBreakdown, score_case
from analysis.management import evaluate_case, management_queue, population_summary
from config.criteria_config import CriteriaConfig
from config.criterion_catalog import criterion_catalog
from data.cleaner import CaseBundle, build_cases, build_task_pseudo_cases
from data.validator import NoteRecord, TaskRecord, ValidationSummary


@dataclass
class Dataset:
    notes: list[NoteRecord]
    tasks: list[TaskRecord]
    cases: dict[str, CaseBundle]
    unmatched_tasks: list[TaskRecord]
    notes_summary: ValidationSummary
    tasks_summary: ValidationSummary








def score_all(cases: dict[str, CaseBundle], config: CriteriaConfig,
              ai_results: dict[str, dict] | None = None, unit: str = "case", rule_settings: dict | None = None) -> dict[str, CaseScoreBreakdown]:
    ai_results = ai_results or {}
    return {key: score_case(case, config, ai_results.get(key), unit=unit, rule_settings=rule_settings) for key, case in cases.items()}


@dataclass
class PeriodResult:
    cases: dict[str, CaseBundle]
    scores: dict[str, CaseScoreBreakdown]
    ai_errors: dict[str, str]






def run_general_analysis(
    dataset: Dataset, config: CriteriaConfig, ai_settings: AISettings,
    progress_cb: Callable[[str, int, int], None] | None = None,
    expert_filter: set[str] | None = None, unit: str = "case", force_ai: bool = False,
    cancel_check: Callable[[], None] | None = None,
    case_filter: set[str] | None = None,
    suspicious_rules: dict | None = None,
    rule_settings: dict | None = None,
) -> dict:
    """Analyze the current dataset as one independent population."""
    def progress(i, n, key):
        if progress_cb:
            progress_cb("تحلیل کلی", i, n)

    evaluation_at = datetime.now().astimezone().isoformat()
    rule_settings = {**(rule_settings or {}), "evaluation_at": evaluation_at}

    if unit == "task":
        tasks = dataset.tasks
        if expert_filter:
            tasks = [t for t in tasks if (t.created_by or "") in expert_filter]
        cases = build_task_pseudo_cases(tasks)
    else:
        cases = dict(dataset.cases)
        if expert_filter:
            cases = {k: v for k, v in cases.items() if primary_expert(v) in expert_filter}
        if case_filter:
            cases = {k: v for k, v in cases.items() if k in case_filter}
    ai_results, ai_errors = ({}, {}) if unit == "task" else analyze_cases(
        cases, config, ai_settings, progress, force=force_ai, cancel_check=cancel_check
    )
    if progress_cb:
        progress_cb("محاسبه امتیازهای Rule-Based", 0, len(cases))
    scores = score_all(cases, config, ai_results, unit=unit, rule_settings=rule_settings)
    if progress_cb:
        progress_cb("محاسبه امتیازهای Rule-Based", len(cases), len(cases))
    general = PeriodResult(cases=cases, scores=scores, ai_errors=ai_errors)
    quantitative = [evaluate_case(case, evaluation_at, (rule_settings or {}).get("management_thresholds"))
                    for case in cases.values()]
    # Keep qualitative violations alongside quantitative results: averages must
    # not hide a failed mandatory criterion or missing evidence.
    by_key = {row["case_key"]: row for row in quantitative}
    definitions = {criterion.id: criterion for _, criterion in config.active_criteria()}
    for key, breakdown in scores.items():
        for criterion in breakdown.criterion_scores:
            definition = definitions.get(criterion.criterion_id)
            if criterion.evaluation_type != "AI":
                continue
            by_key[key]["criteria"].append({
                "id": criterion.criterion_id, "name": criterion.name_fa,
                "category": "qualitative", "value": criterion.score,
                "threshold": definition.pass_threshold if definition else None,
                "status": criterion.status, "unit": "امتیاز از ۱۰۰",
                "reason": criterion.evidence, "evidence": criterion.source_events,
                "confidence": criterion.confidence,
                "severity": "warning" if criterion.status == "needs_correction" else "info",
            })

    severity_settings = rule_settings.get("management_severities", {})
    for row in quantitative:
        for criterion in row["criteria"]:
            if criterion["status"] == "needs_correction":
                criterion["severity"] = severity_settings.get(criterion["id"], "warning")

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
    selected_case_ids = set(cases)
    scoped_notes = [n for n in dataset.notes if n.case_key in selected_case_ids]
    selected_task_ids = {id(link.task) for case in cases.values() for link in case.task_links}
    scoped_tasks = [
        t for t in dataset.tasks
        if id(t) in selected_task_ids
    ]
    scoped_unmatched = [
        t for t in dataset.unmatched_tasks
        if id(t) in selected_task_ids
    ]
    if progress_cb:
        progress_cb("محاسبه سلامت داده انتخاب‌شده", 0, 1)
    health_checks, health_index = compute_data_health(
        scoped_notes, scoped_tasks, cases, scoped_unmatched, rule_settings
    )
    if progress_cb:
        progress_cb("محاسبه سلامت داده انتخاب‌شده", 1, 1)
    if progress_cb:
        progress_cb("در حال بررسی موارد نیازمند بررسی", 0, len(cases))
    grouped_violations = {}
    for row in management_queue(quantitative):
        if row["criterion"]["status"] != "needs_correction":
            continue
        grouped_violations.setdefault(row["case_key"], []).append(
            f"{row['criterion']['name']}: {row['criterion']['value']}؛ حدنصاب {row['criterion']['threshold']}"
        )
    suspicious = [SimpleNamespace(case_key=key, case_number=cases[key].case_number,
                                 case_title=cases[key].case_title, reasons=reasons)
                  for key, reasons in grouped_violations.items()]
    if progress_cb:
        progress_cb("در حال بررسی موارد نیازمند بررسی", len(cases), len(cases))
    return {
        "evaluation_at": evaluation_at,
        "criteria_version": "3.0",
        "criterion_catalog": criterion_catalog(config, rule_settings.get("management_thresholds")),
        "effective_criteria": asdict(config),
        "effective_rule_settings": rule_settings,
        "quantitative": quantitative,
        "management_summary": population_summary(cases, quantitative, evaluation_at),
        "management_queue": management_queue(quantitative),
        "attribution_notice": "مالک فعلی با انجام‌دهنده فعالیت یکی نیست؛ تاریخچه مسئولیت برای رتبه‌بندی معتبر در دسترس نیست.",
        "mode": "general", "general": general, "general_score": overall,
        "general_categories": categories, "general_criteria": criteria,
        "general_narrative": (
            f"امتیاز کلی برای {len(cases)} مورد: "
            f"{overall if overall is not None else 'قابل محاسبه نیست'}."
        ),
        "experts_general": experts, "ranking": ranking,
        "data_health_checks": health_checks, "data_health_index": health_index,
        "suspicious": suspicious, "unit": unit,
    }
