from __future__ import annotations

from dataclasses import dataclass

from analysis.scoring import CaseScoreBreakdown
from config.criteria_config import CriteriaConfig
from data.cleaner import CaseBundle


@dataclass
class MetricComparison:
    id: str
    name_fa: str
    period1: float | None
    period2: float | None
    change: float | None
    change_pct: float | None


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def compare_periods(
    cases_p1: dict[str, CaseBundle], scores_p1: dict[str, CaseScoreBreakdown],
    cases_p2: dict[str, CaseBundle], scores_p2: dict[str, CaseScoreBreakdown],
    config: CriteriaConfig,
) -> dict:
    # --- مقایسه در سطح دسته‌بندی
    category_rows: list[MetricComparison] = []
    for cat in config.categories:
        v1 = _avg([b.category_scores.get(cat.id) for b in scores_p1.values() if b.category_scores.get(cat.id) is not None])
        v2 = _avg([b.category_scores.get(cat.id) for b in scores_p2.values() if b.category_scores.get(cat.id) is not None])
        category_rows.append(_build_comparison(cat.id, cat.name_fa, v1, v2))

    # --- مقایسه در سطح معیار (برای تحلیل علت تغییر)
    criterion_rows: list[MetricComparison] = []
    for cat, crit in config.active_criteria():
        v1 = _avg([
            cs.score for b in scores_p1.values() for cs in b.criterion_scores
            if cs.criterion_id == crit.id and cs.score is not None
        ])
        v2 = _avg([
            cs.score for b in scores_p2.values() for cs in b.criterion_scores
            if cs.criterion_id == crit.id and cs.score is not None
        ])
        criterion_rows.append(_build_comparison(crit.id, crit.name_fa, v1, v2))

    overall1 = _avg([b.final_score for b in scores_p1.values() if b.final_score is not None])
    overall2 = _avg([b.final_score for b in scores_p2.values() if b.final_score is not None])
    overall = _build_comparison("overall", "امتیاز کلی", overall1, overall2)

    narrative = _build_narrative(overall, category_rows, criterion_rows, len(cases_p1), len(cases_p2))

    return {
        "overall": overall,
        "categories": category_rows,
        "criteria": criterion_rows,
        "narrative": narrative,
        "case_count_period1": len(cases_p1),
        "case_count_period2": len(cases_p2),
    }


def _build_comparison(id_: str, name_fa: str, v1: float | None, v2: float | None) -> MetricComparison:
    change = round(v2 - v1, 1) if (v1 is not None and v2 is not None) else None
    change_pct = round((v2 - v1) / v1 * 100, 1) if (v1 not in (None, 0) and v2 is not None) else None
    return MetricComparison(id=id_, name_fa=name_fa, period1=v1, period2=v2, change=change, change_pct=change_pct)


def _build_narrative(
    overall: MetricComparison, categories: list[MetricComparison], criteria: list[MetricComparison],
    n1: int, n2: int,
) -> str:
    """توضیح Rule-Based (بدون AI) علت تغییر، صرفاً بر اساس بزرگ‌ترین Deltaها.
    اگر AI فعال باشد، ماژول ai/analyzer.py می‌تواند همین اعداد را به‌عنوان
    Ground Truth بگیرد و روایت روان‌تری تولید کند؛ اما این تابع بدون نیاز به AI
    هم کار می‌کند (طبق الزام Fallback بدون AI در پرامپت)."""
    if overall.change is None:
        return "برای مقایسه، در هر دو دوره باید حداقل یک Case با امتیاز قابل‌محاسبه وجود داشته باشد."

    direction = "بهبود" if overall.change > 0 else ("افت" if overall.change < 0 else "ثبات")
    lines = [
        f"امتیاز کلی از {overall.period1} به {overall.period2} تغییر کرد ({'+' if overall.change>=0 else ''}{overall.change} نمره)؛ روند کلی: {direction}.",
        f"تعداد Case تحلیل‌شده: دوره اول {n1}، دوره دوم {n2}.",
    ]
    ranked = [c for c in criteria if c.change is not None]
    ranked.sort(key=lambda c: c.change, reverse=True)
    improved = [c for c in ranked if c.change > 3][:3]
    worsened = [c for c in ranked if c.change < -3][-3:]
    if improved:
        parts = "، ".join(f"«{c.name_fa}» (+{c.change})" for c in improved)
        lines.append(f"مهم‌ترین عوامل بهبود: {parts}.")
    if worsened:
        parts = "، ".join(f"«{c.name_fa}» ({c.change})" for c in worsened)
        lines.append(f"مهم‌ترین عوامل افت: {parts}.")
    if not improved and not worsened:
        lines.append("تغییر معنادار در سطح تک‌معیارها مشاهده نشد؛ تغییر کلی احتمالاً ناشی از پراکندگی داده است.")
    return " ".join(lines)
