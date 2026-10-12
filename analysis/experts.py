from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from analysis.rules import PORTAL_AUTHORS
from analysis.scoring import CaseScoreBreakdown
from data.cleaner import CaseBundle


def primary_expert(case: CaseBundle) -> str:
    """Current owner for filtering only, never attribution of historical performance."""
    return (case.owner or "").strip() or "نامشخص؛ تاریخچه مسئولیت موجود نیست"


@dataclass
class ExpertStats:
    expert: str
    case_count: int = 0
    note_count: int = 0
    task_count: int = 0
    objective_scores: list[float] = field(default_factory=list)
    ai_scores: list[float] = field(default_factory=list)
    final_scores: list[float] = field(default_factory=list)
    weak_criteria: Counter = field(default_factory=Counter)
    strong_criteria: Counter = field(default_factory=Counter)
    # نمونه‌های خام هر معیار برای این کارشناس: [(case_key, case_number, case_title, score, evidence, category), ...]
    # برای ساخت Evidence واقعی پشت هر Strength/Weakness (نه فقط شمارش)، بدون نیاز به تغییر در Scoring Engine.
    criterion_samples: dict = field(default_factory=lambda: defaultdict(list))

    @property
    def avg_objective(self) -> float | None:
        return round(sum(self.objective_scores) / len(self.objective_scores), 1) if self.objective_scores else None

    @property
    def avg_ai(self) -> float | None:
        return round(sum(self.ai_scores) / len(self.ai_scores), 1) if self.ai_scores else None

    @property
    def avg_final(self) -> float | None:
        return round(sum(self.final_scores) / len(self.final_scores), 1) if self.final_scores else None


def aggregate_experts(
    cases: dict[str, CaseBundle], scores: dict[str, CaseScoreBreakdown]
) -> dict[str, ExpertStats]:
    stats: dict[str, ExpertStats] = {}
    for key, case in cases.items():
        expert = primary_expert(case)
        s = stats.setdefault(expert, ExpertStats(expert=expert))
        s.case_count += 1
        s.note_count += len(case.notes)
        s.task_count += len(case.tasks)
        # Case quality cannot be attributed to the current owner without a
        # validated responsibility history. Keep workload counts, not rankings.
    return stats


def build_employee_feedback(s: ExpertStats, strength_threshold: float = 80.0,
                             weakness_threshold: float = 60.0, top_n: int = 5) -> dict:
    """از نمونه‌های خام هر معیار برای یک کارشناس، فهرست Strength/Weakness با
    Evidence واقعی + جملات Feedback به سبک «واقعیت به‌جای قضاوت کلی» می‌سازد.
    هیچ عددی اینجا توسط AI تولید نمی‌شود؛ همه از میانگین امتیازهای واقعی محاسبه‌شده‌اند."""

    def summarize(criterion_name: str, samples: list) -> dict:
        scores = [x["score"] for x in samples]
        avg = round(sum(scores) / len(scores), 1)
        low_or_high = sorted(samples, key=lambda x: x["score"])
        return {
            "criterion": criterion_name,
            "category": samples[0]["category"],
            "avg_score": avg,
            "count": len(samples),
            "sample_cases": low_or_high[:3],
        }

    strengths, weaknesses = [], []
    for name, samples in s.criterion_samples.items():
        if len(samples) < 1:
            continue
        summary = summarize(name, samples)
        if summary["avg_score"] >= strength_threshold:
            strengths.append(summary)
        elif summary["avg_score"] < weakness_threshold:
            weaknesses.append(summary)

    strengths.sort(key=lambda x: (-x["avg_score"], -x["count"]))
    weaknesses.sort(key=lambda x: (x["avg_score"], -x["count"]))
    strengths, weaknesses = strengths[:top_n], weaknesses[:top_n]

    feedback_lines = []
    for w in weaknesses:
        feedback_lines.append(
            f"در معیار «{w['criterion']}»، میانگین امتیاز {w['avg_score']} از ۱۰۰ در {w['count']} Case بررسی‌شده ثبت شده است."
        )
    for st in strengths:
        feedback_lines.append(
            f"در معیار «{st['criterion']}»، عملکرد ثابت و قوی با میانگین {st['avg_score']} از ۱۰۰ در {st['count']} Case مشاهده می‌شود."
        )

    action_plan = [
        {"priority": i + 1, "focus": w["criterion"], "category": w["category"],
         "target": f"میانگین ≥ {int(weakness_threshold + 20)}"}
        for i, w in enumerate(weaknesses[:5])
    ]

    return {
        "strengths": strengths, "weaknesses": weaknesses,
        "feedback_lines": feedback_lines, "action_plan": action_plan,
    }


def weakness_priority(avg_score: float) -> str:
    if avg_score < 40:
        return "بالا"
    if avg_score < 55:
        return "متوسط"
    return "پایین"


def team_average(all_stats: dict[str, ExpertStats]) -> float | None:
    values = [s.avg_final for s in all_stats.values() if s.avg_final is not None]
    return round(sum(values) / len(values), 1) if values else None


def build_full_employee_report(
    expert: str,
    s_current: ExpertStats | None,
    all_stats_current: dict[str, ExpertStats],
    period_label: str,
    unit: str = "case",
) -> dict:
    """گزارش کامل و مستقل یک کارشناس: خلاصه عملکرد + کارنامه معیارها + نقاط
    قوت/ضعف اولویت‌بندی‌شده + Feedback + Action Plan + جمع‌بندی مدیریتی.
    گزارش حجم کار مرتبط با مالک فعلی؛ امتیاز فردی بدون تاریخچه مسئولیت تولید نمی‌شود."""
    if not s_current:
        return {
            "expert": expert, "has_data": False,
            "message": "برای این کارشناس در دوره انتخاب‌شده داده‌ای برای تحلیل وجود ندارد.",
        }

    fb = build_employee_feedback(s_current)
    for w in fb["weaknesses"]:
        w["priority"] = weakness_priority(w["avg_score"])


    t_avg = team_average(all_stats_current)
    vs_team = None
    if t_avg is not None and s_current.avg_final is not None:
        vs_team = round(s_current.avg_final - t_avg, 1)

    scorecard = []
    for name, samples in s_current.criterion_samples.items():
        scores = [x["score"] for x in samples]
        scorecard.append({
            "criterion": name, "category": samples[0]["category"],
            "avg_score": round(sum(scores) / len(scores), 1),
            "count": len(samples),
        })
    scorecard.sort(key=lambda x: x["avg_score"])

    top_strength = fb["strengths"][0]["criterion"] if fb["strengths"] else None
    top_weakness = fb["weaknesses"][0]["criterion"] if fb["weaknesses"] else None

    management_summary = {
        "overall_status": "تاریخچه مسئولیت موجود نیست؛ رتبه‌بندی عملکرد فرد انجام نمی‌شود.",
        "top_strength": top_strength or "داده کافی برای شناسایی نقطه قوت مشخص نیست",
        "top_weakness": top_weakness or "داده کافی برای قضاوت عملکرد فردی موجود نیست",
        "top_priority": fb["action_plan"][0]["focus"] if fb["action_plan"] else "—",
        "next_focus": (
            f"تمرکز دوره بعد: بهبود «{top_weakness}»" if top_weakness
            else "تکمیل تاریخچه مسئولیت پیش از قضاوت عملکرد فردی"
        ),
    }

    return {
        "expert": expert, "has_data": True, "unit": unit, "period_label": period_label,
        "summary": {
            "case_count": s_current.case_count if unit == "case" else s_current.task_count,
            "note_count": s_current.note_count, "task_count": s_current.task_count,
            "avg_objective": s_current.avg_objective, "avg_ai": s_current.avg_ai,
            "avg_final": s_current.avg_final,
            "team_average": t_avg, "vs_team_average": vs_team,
        },
        "scorecard": scorecard,
        "strengths": fb["strengths"], "weaknesses": fb["weaknesses"],
        "feedback_lines": fb["feedback_lines"], "action_plan": fb["action_plan"],
        "management_summary": management_summary,
    }
