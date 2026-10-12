"""Conservative time evaluation; all durations are calendar hours."""
from datetime import datetime, timezone


def utc_naive(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def assessment_time(settings):
    # A caller must freeze this once for the entire assessment.
    return utc_naive((settings or {}).get("evaluation_at"))


def is_completed(task):
    if getattr(task, "state_code", None) is not None:
        return str(task.state_code) == "1"
    return (task.status_reason or "").strip().casefold() in {"completed", "تکمیل شده", "تکمیل‌شده"}


def task_deadlines(case, at):
    rows = []
    for task in case.tasks:
        due = utc_naive(task.due_date)
        if not due:
            continue
        finish = utc_naive(getattr(task, "actual_end", None))
        row = {"task_id": task.task_id, "due_at": due.isoformat(), "delay_hours": None}
        if str(getattr(task, "state_code", "")) == "2":
            row["state"] = "not_applicable"
        elif is_completed(task):
            if finish is None or (task.created_on and finish < utc_naive(task.created_on)) or (at and finish > at):
                row["state"] = "insufficient_data"
            else:
                row.update(state="completed", delay_hours=max(0, (finish - due).total_seconds() / 3600))
        elif at is None:
            row["state"] = "insufficient_data"
        elif due > at:
            row["state"] = "not_due"
        else:
            row.update(state="open_overdue", delay_hours=max(0, (at - due).total_seconds() / 3600))
        rows.append(row)
    return rows


def due_date_compliance(case, settings=None):
    from analysis.rules import RuleResult
    rows = task_deadlines(case, assessment_time(settings))
    eligible = [row for row in rows if row["state"] in {"completed", "open_overdue"}]
    if not eligible:
        return RuleResult(None, "موعد هنوز نرسیده یا زمان واقعی پایان/زمان ارزیابی موجود نیست؛ ایجاد و شروع Task جایگزین پایان نیست.")
    delays = sum(row["delay_hours"] > 0 for row in eligible)
    return RuleResult(None, f"{delays} فعالیت دیرکرد دارد از {len(eligible)} فعالیت قابل‌محاسبه؛ جزئیات بر حسب ساعت تقویمی است. حدنصاب امتیازدهی تعریف نشده است.")


def followup_delay(case, settings=None):
    from analysis.rules import RuleResult
    at = assessment_time(settings)
    planned = [task for task in case.tasks if (task.follow_up_needed or "").casefold() in {"yes", "بله"} and task.next_follow_up]
    if not planned:
        return RuleResult(None, "پیگیری برنامه‌ریزی‌شده مرتبط موجود نیست.")
    if at is None:
        return RuleResult(None, "زمان ارزیابی ثابت مشخص نیست.")
    not_due = sum(date > at for task in planned if (date := utc_naive(task.next_follow_up)) is not None)
    return RuleResult(None, f"{not_due} پیگیری هنوز به موعد نرسیده است. برای بقیه، ارتباط صریح فعالیت انجام‌شده با پیگیری لازم است؛ رویداد بعدی به‌تنهایی اثبات انجام پیگیری نیست.")


def first_response_time(case, settings=None):
    from analysis.rules import RuleResult
    created = utc_naive(case.created_on)
    responses = [utc_naive(getattr(note, "created_on", None)) for note in case.notes
                 if getattr(note, "is_customer_response", None) is True]
    responses = [date for date in responses if date is not None]
    if not created or not responses:
        return RuleResult(None, "اولین پاسخ واقعی مشتری نیازمند رویداد ارتباطی صریح است؛ ایجاد Task یا ویرایش Note معادل پاسخ مشتری نیست.")
    first = min(responses)
    at = assessment_time(settings)
    if first < created or (at and first > at):
        return RuleResult(None, "ترتیب زمانی پاسخ مشتری نامعتبر است.")
    hours = (first - created).total_seconds() / 3600
    return RuleResult(None, f"اولین پاسخ مشتری: {hours:.2f} ساعت تقویمی؛ حدنصاب کسب‌وکار تعریف نشده است.")
