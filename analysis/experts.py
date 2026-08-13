from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from analysis.rules import PORTAL_AUTHORS
from analysis.scoring import CaseScoreBreakdown
from data.cleaner import CaseBundle


def primary_expert(case: CaseBundle) -> str:
    """کارشناس اصلی Case: نویسنده‌ای که بیشترین حجم متن کارشناسی را ثبت کرده.
    اگر Note کارشناسی وجود نداشته باشد، ایجادکننده Taskها ملاک قرار می‌گیرد."""
    volume: Counter[str] = Counter()
    for n in case.notes:
        author = (n.note_author or "").strip()
        if not author or author.casefold() in PORTAL_AUTHORS:
            continue
        volume[author] += max(len((n.description or "").strip()), 1)
    if volume:
        return volume.most_common(1)[0][0]
    for t in case.tasks:
        if t.created_by:
            volume[t.created_by] += 1
    if volume:
        return volume.most_common(1)[0][0]
    return "نامشخص"


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
        breakdown = scores.get(key)
        if not breakdown:
            continue
        if breakdown.objective_score is not None:
            s.objective_scores.append(breakdown.objective_score)
        if breakdown.ai_score is not None:
            s.ai_scores.append(breakdown.ai_score)
        if breakdown.final_score is not None:
            s.final_scores.append(breakdown.final_score)
        for cs in breakdown.criterion_scores:
            if cs.score is None:
                continue
            if cs.score < 50:
                s.weak_criteria[cs.name_fa] += 1
            elif cs.score >= 85:
                s.strong_criteria[cs.name_fa] += 1
            s.criterion_samples[cs.name_fa].append({
                "case_key": key, "case_number": case.case_number, "case_title": case.case_title,
                "score": cs.score, "evidence": cs.evidence, "category": cs.category_name_fa,
            })
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
    s_previous: ExpertStats | None,
    all_stats_current: dict[str, ExpertStats],
    period_label: str,
    unit: str = "case",
) -> dict:
    """گزارش کامل و مستقل یک کارشناس: خلاصه عملکرد + کارنامه معیارها + نقاط
    قوت/ضعف اولویت‌بندی‌شده + Feedback + Action Plan + جمع‌بندی مدیریتی.
    همه بر اساس دوره «current» (معمولاً دوره دوم) محاسبه می‌شود؛ دوره
    «previous» فقط برای محاسبه روند (Trend) استفاده می‌شود."""
    if not s_current:
        return {
            "expert": expert, "has_data": False,
            "message": "برای این کارشناس در دوره انتخاب‌شده داده‌ای برای تحلیل وجود ندارد.",
        }

    fb = build_employee_feedback(s_current)
    for w in fb["weaknesses"]:
        w["priority"] = weakness_priority(w["avg_score"])

    change = None
    if s_previous and s_previous.avg_final is not None and s_current.avg_final is not None:
        change = round(s_current.avg_final - s_previous.avg_final, 1)

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
        "overall_status": status_label(change) if change is not None else "داده کافی برای مقایسه با دوره قبل نیست",
        "top_strength": top_strength or "داده کافی برای شناسایی نقطه قوت مشخص نیست",
        "top_weakness": top_weakness or "ضعف قابل‌توجهی شناسایی نشد",
        "top_priority": fb["action_plan"][0]["focus"] if fb["action_plan"] else "—",
        "next_focus": (
            f"تمرکز دوره بعد: بهبود «{top_weakness}»" if top_weakness
            else "روند فعلی حفظ شود"
        ),
    }

    return {
        "expert": expert, "has_data": True, "unit": unit, "period_label": period_label,
        "summary": {
            "case_count": s_current.case_count if unit == "case" else s_current.task_count,
            "note_count": s_current.note_count, "task_count": s_current.task_count,
            "avg_objective": s_current.avg_objective, "avg_ai": s_current.avg_ai,
            "avg_final": s_current.avg_final, "change_vs_previous": change,
            "team_average": t_avg, "vs_team_average": vs_team,
        },
        "scorecard": scorecard,
        "strengths": fb["strengths"], "weaknesses": fb["weaknesses"],
        "feedback_lines": fb["feedback_lines"], "action_plan": fb["action_plan"],
        "management_summary": management_summary,
    }


def status_label(change: float | None) -> str:
    if change is None:
        return "داده کافی نیست"
    if change >= 10:
        return "بهبود قابل توجه"
    if change >= 3:
        return "بهبود"
    if change > -3:
        return "ثابت"
    if change > -10:
        return "افت"
    return "افت قابل توجه"


def rank_experts(period1_stats: dict[str, ExpertStats], period2_stats: dict[str, ExpertStats]) -> list[dict]:
    experts = set(period1_stats) | set(period2_stats)
    rows = []
    for e in experts:
        s1 = period1_stats.get(e)
        s2 = period2_stats.get(e)
        v1 = s1.avg_final if s1 else None
        v2 = s2.avg_final if s2 else None
        change = round(v2 - v1, 1) if (v1 is not None and v2 is not None) else None
        rows.append({
            "expert": e,
            "period1_score": v1,
            "period2_score": v2,
            "change": change,
            "status": status_label(change),
            "period1_cases": s1.case_count if s1 else 0,
            "period2_cases": s2.case_count if s2 else 0,
        })
    rows.sort(key=lambda r: (r["change"] is None, -(r["change"] or 0)))
    return rows
