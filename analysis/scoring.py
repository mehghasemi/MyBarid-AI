from __future__ import annotations

from dataclasses import dataclass, field

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
    score: float | None  # None یعنی «قابل‌محاسبه نبود»، نه صفر
    evidence: str
    weight: float


@dataclass
class CaseScoreBreakdown:
    case_key: str
    objective_score: float | None
    ai_score: float | None
    final_score: float | None
    ai_used: bool
    category_scores: dict[str, float | None] = field(default_factory=dict)
    criterion_scores: list[CriterionScore] = field(default_factory=list)


def _weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
    """pairs: list of (score, weight). None وزن‌های صفر یا خالی -> None."""
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return None
    return sum(s * w for s, w in pairs) / total_w


def score_case(
    case: CaseBundle,
    config: CriteriaConfig,
    ai_scores: dict[str, tuple[float, str]] | None = None,
    unit: str = "case",
) -> CaseScoreBreakdown:
    ai_scores = ai_scores or {}
    ai_used = bool(ai_scores)
    criterion_scores: list[CriterionScore] = []
    category_pairs: dict[str, list[tuple[float, float]]] = {}
    objective_pairs: list[tuple[float, float]] = []
    ai_pairs: list[tuple[float, float]] = []

    for cat, crit in config.active_criteria(unit=unit):
        score: float | None = None
        evidence = ""
        if crit.evaluation_type == "RULE":
            fn = RULE_FUNCTIONS.get(crit.id)
            if fn:
                result = fn(case)
                score, evidence = result.score, result.evidence
        elif crit.evaluation_type == "AI":
            if crit.id in ai_scores:
                score, evidence = ai_scores[crit.id]
            else:
                evidence = "AI غیرفعال است یا برای این Case هنوز اجرا نشده."
        elif crit.evaluation_type == "HYBRID":
            fn = RULE_FUNCTIONS.get(crit.id)
            rule_part = fn(case).score if fn else None
            ai_part, ai_evidence = ai_scores.get(crit.id, (None, ""))
            parts = [p for p in (rule_part, ai_part) if p is not None]
            score = sum(parts) / len(parts) if parts else None
            evidence = ai_evidence or (fn(case).evidence if fn else "")

        criterion_scores.append(CriterionScore(
            criterion_id=crit.id, name_fa=crit.name_fa, category_id=cat.id,
            category_name_fa=cat.name_fa, evaluation_type=crit.evaluation_type,
            score=score, evidence=evidence, weight=crit.weight,
        ))
        if score is not None:
            category_pairs.setdefault(cat.id, []).append((score, crit.weight))
            if crit.evaluation_type == "RULE":
                objective_pairs.append((score, crit.weight))
            elif crit.evaluation_type == "AI":
                ai_pairs.append((score, crit.weight))
            elif crit.evaluation_type == "HYBRID":
                objective_pairs.append((score, crit.weight))
                if crit.id in ai_scores:
                    ai_pairs.append((ai_scores[crit.id][0], crit.weight))

    category_scores = {cid: _weighted_avg(pairs) for cid, pairs in category_pairs.items()}
    objective_score = _weighted_avg(objective_pairs)
    ai_score = _weighted_avg(ai_pairs) if ai_used else None

    obj_ratio = config.objective_ai_ratio.get("objective", 0.6)
    ai_ratio = config.objective_ai_ratio.get("ai", 0.4)
    if objective_score is not None and ai_score is not None:
        final_score = objective_score * obj_ratio + ai_score * ai_ratio
    elif objective_score is not None:
        final_score = objective_score
    else:
        final_score = ai_score

    return CaseScoreBreakdown(
        case_key=case.case_key,
        objective_score=_round(objective_score),
        ai_score=_round(ai_score),
        final_score=_round(final_score),
        ai_used=ai_used,
        category_scores={k: _round(v) for k, v in category_scores.items()},
        criterion_scores=criterion_scores,
    )


def _round(v: float | None) -> float | None:
    return round(v, 1) if v is not None else None
