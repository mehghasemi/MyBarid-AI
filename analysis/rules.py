"""Rule Engine مستقل از UI و مستقل از AI.

هر تابع Rule یک Case را می‌گیرد و RuleResult برمی‌گرداند (score بین ۰ تا ۱۰۰،
یا None اگر معیار برای آن Case بی‌معنی/غیرقابل‌محاسبه باشد -- در این حالت
معیار از میانگین‌گیری آن Case کنار گذاشته می‌شود، نه اینکه به‌صورت پیش‌فرض
امتیاز کامل بگیرد).

برای افزودن یک Rule جدید: یک تابع با امضای مشابه بنویسید و در دیکشنری
RULE_FUNCTIONS ثبت کنید؛ نیازی به تغییر بقیه برنامه نیست (فقط اگر بخواهید
آن را در config/default_criteria.json هم فعال کنید، یک ورودی جدید با همان id
اضافه کنید).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from data.cleaner import CaseBundle

PORTAL_AUTHORS = {"portal portal", "پرتال", "customer portal"}

PROBLEM_KEYWORDS = ["مشکل", "خطا", "ایراد", "قطع", "کند", "مسدود", "خرابی", "عدم", "امکان لاگین"]
ACTION_KEYWORDS = ["بررسی", "اقدام", "تماس گرفته شد", "انجام شد", "پیگیری", "تنظیم", "نصب", "اصلاح", "ریست", "تغییر"]
RESULT_KEYWORDS = ["حل شد", "رفع شد", "برطرف شد", "نتیجه", "تست شد", "تایید شد", "کار می‌کند", "مشکل برطرف"]


@dataclass
class RuleResult:
    score: float | None
    evidence: str


def _staff_notes(case: CaseBundle):
    return [n for n in case.notes if (n.note_author or "").strip().casefold() not in PORTAL_AUTHORS]


def _staff_text(case: CaseBundle) -> str:
    return "\n".join(n.description for n in _staff_notes(case) if n.description).strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    low = text.casefold()
    return any(kw.casefold() in low for kw in keywords)


# ---------------------------------------------------------------- Notes ----

def notes_completeness(case: CaseBundle) -> RuleResult:
    text = _staff_text(case)
    if not text:
        return RuleResult(0.0, "هیچ Note کارشناسی با متن ثبت نشده است.")
    hits = [
        ("مشکل", _contains_any(text, PROBLEM_KEYWORDS)),
        ("اقدام", _contains_any(text, ACTION_KEYWORDS)),
        ("نتیجه", _contains_any(text, RESULT_KEYWORDS)),
    ]
    count = sum(1 for _, ok in hits if ok)
    score = round(count / 3 * 100)
    missing = [name for name, ok in hits if not ok]
    evidence = "هر سه بخش (مشکل/اقدام/نتیجه) در Noteها قابل تشخیص است." if not missing \
        else f"در Noteها اشاره‌ای به «{'، '.join(missing)}» یافت نشد."
    return RuleResult(score, evidence)


def notes_clarity(case: CaseBundle) -> RuleResult:
    notes = _staff_notes(case)
    lengths = [len((n.description or "").strip()) for n in notes]
    if not lengths:
        return RuleResult(None, "Note کارشناسی برای ارزیابی وجود ندارد.")
    avg_len = sum(lengths) / len(lengths)
    if avg_len < 20:
        score, note = 20, "میانگین طول متن Noteها بسیار کوتاه است."
    elif avg_len < 50:
        score, note = 50, "متن Noteها کوتاه و کم‌جزئیات است."
    elif avg_len < 150:
        score, note = 78, "متن Noteها در حد قابل قبول توضیح دارد."
    else:
        score, note = 100, "متن Noteها با جزئیات کافی ثبت شده است."
    return RuleResult(score, f"{note} (میانگین {round(avg_len)} کاراکتر)")


def notes_result_recorded(case: CaseBundle) -> RuleResult:
    notes = _staff_notes(case)
    if not notes:
        return RuleResult(None, "Note کارشناسی وجود ندارد.")
    text = _staff_text(case)
    lifecycle = (case.status or "").strip().casefold()
    if lifecycle in {"resolved", "closed"} and not _contains_any(text, RESULT_KEYWORDS):
        if _contains_any(text, ACTION_KEYWORDS):
            return RuleResult(20.0, "Action is recorded, but the actual result or impact is not recorded.")
        return RuleResult(0.0, "Case is closed, but the actual action result is not recorded.")
    if _contains_any(text, RESULT_KEYWORDS):
        return RuleResult(100.0, "عبارتی دال بر ثبت نتیجه اقدام یافت شد.")
    if (case.status or "").strip().casefold() in {"resolved", "closed"}:
        return RuleResult(40.0, "وضعیت Case بسته/حل‌شده است اما نتیجه اقدام صراحتاً در متن ثبت نشده.")
    return RuleResult(15.0, "نتیجه اقدام در متن Noteها ذکر نشده است.")


def notes_no_duplication(case: CaseBundle) -> RuleResult:
    notes = [n for n in case.notes if n.description]
    if len(notes) <= 1:
        return RuleResult(None, "برای بررسی تکرار، حداقل دو Note لازم است.")
    seen = set()
    dup = 0
    for n in notes:
        sig = " ".join(n.description.split()).casefold()[:300]
        if sig in seen:
            dup += 1
        else:
            seen.add(sig)
    ratio = dup / len(notes)
    score = round((1 - ratio) * 100)
    evidence = "Note تکراری یافت نشد." if dup == 0 else f"{dup} Note تکراری از {len(notes)} Note شناسایی شد."
    return RuleResult(score, evidence)


def notes_writing_quality(case: CaseBundle) -> RuleResult:
    notes = _staff_notes(case)
    if not notes:
        return RuleResult(None, "Note کارشناسی وجود ندارد.")
    word_counts = [len((n.description or "").split()) for n in notes]
    avg_words = sum(word_counts) / len(word_counts)
    if avg_words < 3:
        return RuleResult(20.0, "متن Noteها عمدتاً تک‌کلمه‌ای/بسیار مختصر است.")
    if avg_words < 8:
        return RuleResult(55.0, "متن Noteها ساختار محدودی دارد.")
    if avg_words < 20:
        return RuleResult(80.0, "متن Noteها ساختار قابل قبولی دارد.")
    return RuleResult(95.0, "متن Noteها دارای ساختار و جزئیات کافی است.")


# ---------------------------------------------------------------- Tasks ----

def task_presence_when_needed(case: CaseBundle) -> RuleResult:
    # A Task is required only when the source explicitly indicates an L2
    # hand-off. Note count, or task absence itself, is not evidence.
    explicit_text = " ".join(filter(None, [
        case.scenario, case.case_description, case.status_reason, _staff_text(case),
    ])).casefold()
    l2_markers = (
        "l2", "level 2", "second level", "tier 2",
        "لایه دو", "لایه ۲", "سطح دو", "سطح ۲", "ارجاع به لایه",
    )
    if not any(marker.casefold() in explicit_text for marker in l2_markers):
        return RuleResult(None, "N/A / Insufficient Evidence: داده معتبر برای الزام ارجاع به لایه دو یا ایجاد Task وجود ندارد.")
    if case.tasks:
        return RuleResult(100.0, f"ارجاع به لایه دو در داده ثبت شده و {len(case.tasks)} Task وجود دارد.")
    return RuleResult(0.0, "ارجاع به لایه دو در داده ثبت شده، اما Task متناظر وجود ندارد.")


def task_case_relation(case: CaseBundle) -> RuleResult:
    if not case.task_links:
        return RuleResult(None, "Task مرتبطی وجود ندارد.")
    weights = {"high": 100, "medium": 70, "low": 40}
    scores = [weights[tl.confidence] for tl in case.task_links]
    avg = sum(scores) / len(scores)
    low_count = sum(1 for tl in case.task_links if tl.confidence != "high")
    evidence = "اتصال همه Taskها به این Case قطعی است (بر اساس شماره Case)." if low_count == 0 \
        else f"اتصال {low_count} Task از {len(case.task_links)} بر اساس تطبیق متنی Regarding با عنوان Case انجام شده (نه شماره Case)."
    return RuleResult(round(avg), evidence)


def task_description_quality(case: CaseBundle) -> RuleResult:
    if not case.tasks:
        return RuleResult(None, "Task‌ای برای ارزیابی وجود ندارد.")
    texts = [(t.description or "").strip() for t in case.tasks]
    non_empty = [t for t in texts if t]
    if not non_empty:
        return RuleResult(0.0, "هیچ Task ای دارای Description نیست.")
    avg_len = sum(len(t) for t in non_empty) / len(non_empty)
    ratio_filled = len(non_empty) / len(texts)
    base = 20 if avg_len < 20 else (55 if avg_len < 50 else (85 if avg_len < 150 else 100))
    score = round(base * ratio_filled)
    evidence = f"{len(non_empty)} از {len(texts)} Task دارای Description است (میانگین طول {round(avg_len)} کاراکتر)."
    return RuleResult(score, evidence)


def task_result_recorded(case: CaseBundle) -> RuleResult:
    if not case.tasks:
        return RuleResult(None, "Task‌ای برای ارزیابی وجود ندارد.")
    texts = [(t.description or "") for t in case.tasks]
    joined = "\n".join(texts)
    completed = [t for t in case.tasks if (t.status_reason or "").strip().casefold() in {"completed", "closed"}]
    if _contains_any(joined, RESULT_KEYWORDS):
        return RuleResult(100.0, "نتیجه اقدام در متن Task ثبت شده است.")
    if completed:
        return RuleResult(45.0, "Task با وضعیت تکمیل‌شده ثبت شده اما نتیجه به‌صراحت در متن نیامده است.")
    return RuleResult(20.0, "نتیجه اقدام Task مشخص نیست.")


# ------------------------------------------------------------ Timing -----

def first_response_time(case: CaseBundle) -> RuleResult:
    anchor = case.created_on or (min((n.note_date for n in case.notes if n.note_date), default=None))
    staff_set = set(id(n) for n in _staff_notes(case))
    staff_events = [(kind, when, obj) for kind, when, obj in case.all_events_sorted
                    if kind == "task" or (kind == "note" and id(obj) in staff_set)]
    if not anchor or not staff_events:
        return RuleResult(None, "زمان ایجاد Case یا اولین اقدام کارشناسی مشخص نیست.")
    first_when = staff_events[0][1]
    delta_hours = (first_when - anchor).total_seconds() / 3600
    if delta_hours < 0:
        return RuleResult(None, "ترتیب زمانی نامعتبر است (اولین اقدام قبل از ایجاد Case ثبت شده).")
    if delta_hours <= 4:
        score, note = 100, "اولین اقدام کارشناسی ظرف ۴ ساعت انجام شده."
    elif delta_hours <= 24:
        score, note = 80, "اولین اقدام کارشناسی ظرف یک روز کاری انجام شده."
    elif delta_hours <= 72:
        score, note = 55, "اولین اقدام کارشناسی با تأخیر (تا ۳ روز) انجام شده."
    else:
        score, note = 25, "اولین اقدام کارشناسی با تأخیر قابل‌توجه (بیش از ۳ روز) انجام شده."
    return RuleResult(score, f"{note} ({round(delta_hours,1)} ساعت فاصله)")


def followup_delay(case: CaseBundle) -> RuleResult:
    pending = [t for t in case.tasks if (t.follow_up_needed or "").strip().casefold() == "yes" and t.next_follow_up]
    if not pending:
        return RuleResult(None, "Task دارای Follow-up برنامه‌ریزی‌شده برای این Case وجود ندارد.")
    events = case.all_events_sorted
    penalties = []
    for t in pending:
        later = [when for _, when, _ in events if when and when > t.next_follow_up]
        if not later:
            penalties.append(0)
            continue
        gap_days = (later[0] - t.next_follow_up).total_seconds() / 86400
        if gap_days <= 1:
            penalties.append(100)
        elif gap_days <= 3:
            penalties.append(65)
        else:
            penalties.append(25)
    score = round(sum(penalties) / len(penalties))
    evidence = f"از {len(pending)} پیگیری برنامه‌ریزی‌شده، میانگین رعایت زمان {score} از ۱۰۰ است."
    return RuleResult(score, evidence)


def due_date_compliance(case: CaseBundle) -> RuleResult:
    with_due = [t for t in case.tasks if t.due_date]
    if not with_due:
        return RuleResult(None, "Task دارای Due Date برای این Case وجود ندارد.")
    scores = []
    for t in with_due:
        finish = t.actual_start or t.created_on
        if not finish:
            continue
        gap_hours = (finish - t.due_date).total_seconds() / 3600
        if gap_hours <= 0:
            scores.append(100)
        elif gap_hours <= 24:
            scores.append(70)
        else:
            scores.append(30)
    if not scores:
        return RuleResult(None, "امکان محاسبه رعایت Due Date وجود ندارد.")
    score = round(sum(scores) / len(scores))
    return RuleResult(score, f"میانگین رعایت Due Date برای {len(scores)} Task: {score} از ۱۰۰.")


def unusual_time_gap(case: CaseBundle) -> RuleResult:
    events = [when for _, when, _ in case.all_events_sorted if when]
    if len(events) < 2:
        return RuleResult(None, "برای بررسی فاصله زمانی حداقل دو رویداد لازم است.")
    events.sort()
    gaps_days = [(events[i + 1] - events[i]).total_seconds() / 86400 for i in range(len(events) - 1)]
    max_gap = max(gaps_days)
    is_open = (case.status or "").strip().casefold() not in {"resolved", "closed", "cancelled"}
    threshold = 14 if is_open else 30
    if max_gap <= threshold / 2:
        return RuleResult(100.0, f"بیشترین فاصله بین رویدادها {round(max_gap,1)} روز است.")
    if max_gap <= threshold:
        return RuleResult(65.0, f"فاصله {round(max_gap,1)} روزه بین دو رویداد مشاهده شد.")
    return RuleResult(25.0, f"فاصله غیرمعمول {round(max_gap,1)} روزه بین دو رویداد مشاهده شد.")


# --------------------------------------------------------- Documentation --

# --------------------------------------------------------- Scenario -----

def scenario_recorded(case: CaseBundle) -> RuleResult:
    """کیفیت ثبت فیلد Scenario (سناریوی وقوع مشکل). این فیلد را کارشناس
    هنگام ثبت/مدیریت Case وارد می‌کند و طبق تعریف Rule-Based زیر ارزیابی
    می‌شود (نه با قضاوت سلیقه‌ای):
    - خالی -> امتیاز صفر
    - بسیار کوتاه (کمتر از ۱۵ کاراکتر) -> امتیاز پایین
    - حاوی توضیح معنادار -> امتیاز بالا، به‌خصوص اگر با کلیدواژه‌های
      مشکل/اقدام همپوشانی داشته باشد (نشان‌دهنده توضیح واقعی سناریو، نه
      یک متن جایگزین بی‌ربط)."""
    text = (case.scenario or "").strip()
    if not text:
        return RuleResult(0.0, "فیلد Scenario برای این Case خالی است.")
    if len(text) < 15:
        return RuleResult(30.0, f"فیلد Scenario بسیار کوتاه است ({len(text)} کاراکتر).")
    if _contains_any(text, PROBLEM_KEYWORDS):
        return RuleResult(100.0, "فیلد Scenario شامل توضیح مرتبط با مشکل گزارش‌شده است.")
    return RuleResult(70.0, f"فیلد Scenario ثبت شده است ({len(text)} کاراکتر) ولی اشاره مستقیمی به مشکل در آن یافت نشد.")


def timeline_reconstructable(case: CaseBundle) -> RuleResult:
    events = case.all_events_sorted
    if len(events) < 1:
        return RuleResult(0.0, "هیچ رویداد دارای تاریخ معتبر برای این Case ثبت نشده است.")
    if len(events) == 1:
        return RuleResult(55.0, "فقط یک رویداد دارای تاریخ ثبت شده؛ بازسازی روند محدود است.")
    return RuleResult(95.0, f"{len(events)} رویداد به‌ترتیب زمانی قابل بازسازی است.")


def final_status_clear(case: CaseBundle) -> RuleResult:
    events = case.all_events_sorted
    if not events:
        return RuleResult(None, "رویداد دارای تاریخ برای تعیین وضعیت نهایی وجود ندارد.")
    last_kind, _, last_obj = events[-1]
    text = (last_obj.description or "") if last_kind == "note" else (last_obj.description or last_obj.subject or "")
    status_known = bool((case.status or "").strip())
    all_staff_text = _staff_text(case)
    if (case.status or "").strip().casefold() in {"resolved", "closed"} and not _contains_any(all_staff_text, RESULT_KEYWORDS):
        return RuleResult(20.0, "Case is closed, but the actual result is not documented in the staff note; Status alone is insufficient.")
    if _contains_any(text, RESULT_KEYWORDS) and status_known:
        return RuleResult(100.0, "وضعیت نهایی هم در فیلد Status و هم در متن آخرین رویداد مشخص است.")
    if status_known:
        return RuleResult(60.0, "فیلد Status مقداردهی شده اما متن آخرین رویداد نتیجه صریحی ندارد.")
    return RuleResult(20.0, "نه فیلد Status و نه متن آخرین رویداد، نتیجه نهایی روشنی ندارند.")


# ------------------------------------------------- Task-level (پشتیبانی فنی) --
# این توابع مستقیماً روی یک Task مستقل کار می‌کنند (نه در بستر کل Case) و برای
# کارشناسان پشتیبانی فنی استفاده می‌شوند که واحد ارزیابی آن‌ها Task است، نه Case.
# چون هر Task در این حالت به‌صورت یک «شبه‌Case» تک‌عضوی (data/cleaner.py:
# build_task_pseudo_cases) نمایش داده می‌شود، می‌توان همان توابع Rule موجودِ
# task_description_quality و task_result_recorded و due_date_compliance را
# مستقیماً و بدون تغییر روی آن اجرا کرد (چون این توابع از ابتدا روی «همه
# Taskهای یک Case» کار می‌کنند و برای Case تک‌Task هم درست جواب می‌دهند).

def task_std_followup_handled(case: CaseBundle) -> RuleResult:
    if not case.tasks:
        return RuleResult(None, "Task ای برای ارزیابی وجود ندارد.")
    t = case.tasks[0]
    needs_followup = (t.follow_up_needed or "").strip().casefold() == "yes"
    if not needs_followup:
        return RuleResult(None, "این Task نیاز به Follow-up نداشته است.")
    if t.next_follow_up:
        return RuleResult(100.0, "تاریخ Follow-up بعدی برای این Task ثبت شده است.")
    return RuleResult(20.0, "این Task نیاز به Follow-up داشته اما تاریخ Follow-up بعدی ثبت نشده است.")


RULE_FUNCTIONS_TASK = {
    "task_std_description_quality": task_description_quality,
    "task_std_result_recorded": task_result_recorded,
    "task_std_due_date_compliance": due_date_compliance,
    "task_std_followup_handled": task_std_followup_handled,
}

RULE_FUNCTIONS = {
    "notes_completeness": notes_completeness,
    "notes_clarity": notes_clarity,
    "notes_result_recorded": notes_result_recorded,
    "notes_no_duplication": notes_no_duplication,
    "notes_writing_quality": notes_writing_quality,
    "task_presence_when_needed": task_presence_when_needed,
    "task_case_relation": task_case_relation,
    "task_description_quality": task_description_quality,
    "task_result_recorded": task_result_recorded,
    "first_response_time": first_response_time,
    "followup_delay": followup_delay,
    "due_date_compliance": due_date_compliance,
    "unusual_time_gap": unusual_time_gap,
    "timeline_reconstructable": timeline_reconstructable,
    "final_status_clear": final_status_clear,
    "scenario_recorded": scenario_recorded,
    **RULE_FUNCTIONS_TASK,
}
