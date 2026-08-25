from __future__ import annotations

from dataclasses import dataclass, field

from data.cleaner import CaseBundle


LIFECYCLE_STATUSES = {"open", "resolved", "closed", "cancelled"}
OUTCOME_STATUSES = {"solved", "partially solved", "unresolved", "blocked", "unknown"}


@dataclass
class CaseOutcome:
    lifecycle_status: str | None
    outcome_status: str | None
    evidence: list[str] = field(default_factory=list)
    confidence: str = "low"
    coverage: float = 0.0
    na_reason: str | None = None


def classify_case_outcome(case: CaseBundle) -> CaseOutcome:
    lifecycle = (case.status or "").strip() or None
    lifecycle_key = lifecycle.casefold() if lifecycle else ""
    lifecycle_value = lifecycle.title() if lifecycle_key in LIFECYCLE_STATUSES else lifecycle

    if not lifecycle:
        return CaseOutcome(
            lifecycle_status=None,
            outcome_status=None,
            evidence=[],
            confidence="low",
            coverage=0.0,
            na_reason="Lifecycle برای تعیین نتیجه واقعی وجود ندارد.",
        )

    texts = [
        *(n.description or "" for n in case.notes),
        *(t.description or "" for t in case.tasks),
    ]
    joined = "\n".join(texts).casefold()

    if any(token in joined for token in ("حل شد", "رفع شد", "برطرف شد", "solved", "resolved")):
        outcome, evidence = "Solved", ["نتیجهٔ حل‌شدن در متن رویداد ثبت شده است."]
    elif any(token in joined for token in ("نیمه حل", "partially solved")):
        outcome, evidence = "Partially Solved", ["نتیجهٔ ناقص در متن رویداد ثبت شده است."]
    elif any(token in joined for token in ("مسدود", "blocked")):
        outcome, evidence = "Blocked", ["عبارت مسدودشدن در متن رویداد ثبت شده است."]
    elif lifecycle_key in {"resolved", "closed"}:
        outcome, evidence = "Unknown", ["Lifecycle بسته/حل‌شده است اما نتیجهٔ واقعی صریح نیست."]
    else:
        outcome, evidence = None, []

    if not lifecycle and outcome is None:
        return CaseOutcome(
            lifecycle_status=None,
            outcome_status=None,
            evidence=[],
            confidence="low",
            coverage=0.0,
            na_reason="Lifecycle و شواهد نتیجه در دادهٔ ورودی وجود ندارد.",
        )

    coverage = 1.0 if lifecycle and outcome else 0.5 if lifecycle or outcome else 0.0
    confidence = "high" if coverage == 1.0 else "low"
    return CaseOutcome(
        lifecycle_status=lifecycle_value,
        outcome_status=outcome or "Unknown",
        evidence=evidence,
        confidence=confidence,
        coverage=coverage,
        na_reason=None if outcome else "نتیجهٔ واقعی مورد از دادهٔ موجود قابل تعیین نیست.",
    )
