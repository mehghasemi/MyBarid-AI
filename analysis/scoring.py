from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from analysis.rules import RULE_FUNCTIONS
from config.criteria_config import CriteriaConfig
from data.cleaner import CaseBundle


@dataclass
class CriterionScore:
    criterion_id: str
    name_fa: str
    category_id: str
    category_name_fa: str
    evaluation_type: str
    score: float | None
    evidence: str
    weight: float
    coverage: float = 0.0
    confidence: str = "low"
    na_reason: str | None = None
    source_events: list[dict[str, Any]] = field(default_factory=list)
    criteria_version: str = "2.0"


@dataclass
class CaseScoreBreakdown:
    case_key: str
    objective_score: float | None
    ai_score: float | None
    final_score: float | None
    ai_used: bool
    category_scores: dict[str, float | None] = field(default_factory=dict)
    criterion_scores: list[CriterionScore] = field(default_factory=list)
    coverage: float = 0.0
    confidence: str = "low"
    na_criteria: int = 0
    criteria_version: str = "2.0"
    outcome_status: str | None = None
    lifecycle_status: str | None = None


def _weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return None
    return sum(score * weight for score, weight in pairs) / total_weight


def _confidence(coverage: float) -> str:
    if coverage >= 0.8:
        return "high"
    if coverage >= 0.6:
        return "medium"
    return "low"


def _derive_outcome_status(case: CaseBundle) -> str | None:
    text = "\n".join(
        [(n.description or "") for n in case.notes]
        + [(t.description or "") for t in case.tasks]
    ).casefold()
    if any(token in text for token in ("حل شد", "رفع شد", "برطرف شد", "solved", "resolved")):
        return "Solved"
    if any(token in text for token in ("مسدود", "blocked", "منتظر")):
        return "Blocked"
    if case.status:
        return "Unknown"
    return None


def score_case(
    case: CaseBundle,
    config: CriteriaConfig,
    ai_scores: dict[str, tuple[float | None, str]] | None = None,
    unit: str = "case",
) -> CaseScoreBreakdown:
    """Score with N/A-aware re-weighting while preserving the legacy API."""
    ai_scores = ai_scores or {}
    ai_used = bool(ai_scores)
    criterion_scores: list[CriterionScore] = []
    category_pairs: dict[str, list[tuple[float, float]]] = {}
    objective_pairs: list[tuple[float, float]] = []
    ai_pairs: list[tuple[float, float]] = []
    profile = config.match_profile(case)
    allowed_criteria = set(profile.criteria_ids) if profile else None
    applicable_weight = 0.0

    for category, criterion in config.active_criteria(unit=unit):
        if allowed_criteria is not None and criterion.id not in allowed_criteria:
            criterion_scores.append(CriterionScore(
                criterion_id=criterion.id,
                name_fa=criterion.name_fa,
                category_id=category.id,
                category_name_fa=category.name_fa,
                evaluation_type=criterion.evaluation_type,
                score=None,
                evidence="",
                weight=criterion.weight,
                coverage=0.0,
                confidence="low",
                na_reason=f"برای پروفایل «{profile.name_fa}» این معیار مرتبط نیست.",
            ))
            continue
        applicable_weight += criterion.weight
        score: float | None = None
        evidence = ""
        na_reason: str | None = None
        confidence = "low"
        coverage = 0.0

        if criterion.evaluation_type == "RULE":
            fn = RULE_FUNCTIONS.get(criterion.id)
            if fn:
                result = fn(case)
                score, evidence = result.score, result.evidence
            else:
                na_reason = f"Rule '{criterion.id}' تعریف نشده است."
                evidence = na_reason
        elif criterion.evaluation_type == "AI":
            if criterion.id in ai_scores:
                score, evidence = ai_scores[criterion.id]
                if score is None:
                    na_reason = evidence or "AI برای این مورد شواهد کافی ندارد."
            else:
                na_reason = "AI غیرفعال است یا برای این مورد خروجی معتبر ندارد."
                evidence = na_reason
        elif criterion.evaluation_type == "HYBRID":
            fn = RULE_FUNCTIONS.get(criterion.id)
            rule_result = fn(case) if fn else None
            ai_part, ai_evidence = ai_scores.get(criterion.id, (None, ""))
            parts = [value for value in (rule_result.score if rule_result else None, ai_part)
                     if value is not None]
            if parts:
                score = sum(parts) / len(parts)
                evidence = ai_evidence or rule_result.evidence
            else:
                na_reason = ai_evidence or "بخش Rule و AI هیچ خروجی قابل اتکایی ندارند."
                evidence = na_reason

        if score is not None:
            coverage = 1.0
            confidence = "medium" if criterion.evaluation_type != "RULE" else "high"
            category_pairs.setdefault(category.id, []).append((score, criterion.weight))
            if criterion.evaluation_type == "AI":
                ai_pairs.append((score, criterion.weight))
            else:
                objective_pairs.append((score, criterion.weight))
        elif not na_reason:
            na_reason = evidence or "دادهٔ کافی برای محاسبه وجود ندارد."

        criterion_scores.append(CriterionScore(
            criterion_id=criterion.id,
            name_fa=criterion.name_fa,
            category_id=category.id,
            category_name_fa=category.name_fa,
            evaluation_type=criterion.evaluation_type,
            score=_round(score),
            evidence=evidence,
            weight=criterion.weight,
            coverage=coverage,
            confidence=confidence,
            na_reason=na_reason,
        ))

    category_scores = {
        category_id: _round(_weighted_avg(pairs))
        for category_id, pairs in category_pairs.items()
    }
    objective_score = _round(_weighted_avg(objective_pairs))
    ai_score = _round(_weighted_avg(ai_pairs)) if ai_pairs else None

    objective_ratio = config.objective_ai_ratio.get("objective", 0.6)
    ai_ratio = config.objective_ai_ratio.get("ai", 0.4)
    if objective_score is not None and ai_score is not None:
        final_score = objective_score * objective_ratio + ai_score * ai_ratio
    elif objective_score is not None:
        final_score = objective_score
    else:
        final_score = ai_score

    active_weight = applicable_weight or sum(c.weight for _, c in config.active_criteria(unit=unit))
    eligible_weight = sum(c.weight for c in criterion_scores if c.score is not None)
    coverage = eligible_weight / active_weight if active_weight else 0.0

    return CaseScoreBreakdown(
        case_key=case.case_key,
        objective_score=objective_score,
        ai_score=ai_score,
        final_score=_round(final_score),
        ai_used=ai_used,
        category_scores=category_scores,
        criterion_scores=criterion_scores,
        coverage=round(coverage, 3),
        confidence=_confidence(coverage),
        na_criteria=sum(1 for item in criterion_scores if item.score is None),
        outcome_status=_derive_outcome_status(case),
        lifecycle_status=case.status,
    )


def _round(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
