"""Evidence-led managerial metrics; no invented history or business thresholds."""
from collections import Counter, defaultdict
from statistics import median

from analysis.timing import utc_naive, task_deadlines

SCHEMA_VERSION = "3.0"
METRICS = {
    "status_dwell": ("ماندگاری در هر وضعیت", "status_history"),
    "current_status_duration": ("مدت پیوسته در وضعیت جاری", "status_history"),
    "status_entries": ("تعداد ورود به هر وضعیت", "status_history"),
    "customer_first_response": ("اولین پاسخ واقعی مشتری", "communication"),
    "internal_first_action": ("اولین اقدام داخلی", "activity"),
    "created_to_resolved": ("ایجاد تا اولین حل", "status_history"),
    "created_to_closed": ("ایجاد تا اولین بستن", "status_history"),
    "waiting_customer": ("انتظار مشتری", "status_history"),
    "waiting_team": ("انتظار تیم داخلی", "status_history"),
    "waiting_third_party": ("انتظار شخص ثالث", "status_history"),
    "inactivity": ("بی‌اقدامی در مورد باز", "complete_activity"),
    "followup_delay": ("تأخیر پیگیری مرتبط", "linked_followup"),
    "task_deadlines": ("رعایت موعد پایان فعالیت", "actualend"),
    "reopens": ("تعداد بازگشایی", "status_history"),
    "owner_changes": ("تغییر مسئول یا تیم", "responsibility_history"),
}


def metric(key, value=None, evidence=None, reason=None, threshold=None):
    status = "insufficient_data" if value is None else "measured"
    if value is not None and isinstance(value, (int, float)) and threshold is not None:
        status = "pass" if value <= threshold else "needs_correction"
    return {"id": key, "name": METRICS[key][0], "value": value,
            "status": status, "threshold": threshold, "unit": "بار" if key in {"status_entries", "reopens", "owner_changes"} else "ساعت تقویمی",
            "confidence": "medium" if value is not None else "low",
            "evidence": evidence or [], "reason": reason,
            "severity": "warning" if status == "needs_correction" else "info"}


def status_intervals(case, at):
    """Consume a complete authoritative history only; never use modifiedon."""
    if not getattr(case, "history_complete", False):
        return None, "تاریخچه کامل تغییر وضعیت از CRM دریافت نشده است."
    history = getattr(case, "status_history", [])
    if not history or at is None:
        return None, "تاریخچه یا زمان ثابت ارزیابی موجود نیست."
    events = []
    seen = set()
    for event in history:
        time = utc_naive(event.get("entered_at"))
        status = event.get("status")
        kind = event.get("kind")
        if time is None or not status or kind not in {"open", "resolved", "closed", "waiting_customer", "waiting_team", "waiting_third_party"} or time > at:
            return None, "زمان، وضعیت یا گروه وضعیت در تاریخچه نامعتبر است."
        sig = (time, status, event.get("event_id"))
        if sig in seen:
            continue
        seen.add(sig)
        if events and status == events[-1][1] and kind == events[-1][2]:
            continue
        if events and time <= events[-1][0]:
            return None, "ترتیب زمانی یا هم‌پوشانی تاریخچه نامعتبر است."
        events.append((time, status, kind, event.get("event_id")))
    if utc_naive(case.created_on) != events[0][0]:
        return None, "بخش ابتدای تاریخچه از زمان ایجاد مورد نامعلوم است."
    intervals = []
    for index, (start, status, kind, event_id) in enumerate(events):
        end = events[index + 1][0] if index + 1 < len(events) else at
        intervals.append({"status": status, "kind": kind, "start": start.isoformat(),
                          "end": end.isoformat(), "hours": (end - start).total_seconds() / 3600,
                          "event_id": event_id})
    return intervals, None


def evaluate_case(case, evaluation_at, thresholds=None):
    at = utc_naive(evaluation_at)
    thresholds = thresholds or {}
    rows = {key: metric(key, reason=f"داده موردنیاز: {source}") for key, (_, source) in METRICS.items()}
    intervals, history_error = status_intervals(case, at)
    if intervals:
        totals = defaultdict(float)
        counts = Counter()
        for interval in intervals:
            totals[interval["status"]] += interval["hours"]
            counts[interval["status"]] += 1
        rows["status_dwell"] = metric("status_dwell", dict(totals), intervals)
        rows["status_entries"] = metric("status_entries", dict(counts), intervals)
        rows["current_status_duration"] = metric("current_status_duration", intervals[-1]["hours"], [intervals[-1]], threshold=thresholds.get("current_status_duration"))
        for key in ("waiting_customer", "waiting_team", "waiting_third_party"):
            rows[key] = metric(key, sum(i["hours"] for i in intervals if i["kind"] == key), intervals, threshold=thresholds.get(key))
        for key, kind in (("created_to_resolved", "resolved"), ("created_to_closed", "closed")):
            entry = next((i for i in intervals if i["kind"] == kind), None)
            if entry:
                hours = (utc_naive(entry["start"]) - utc_naive(case.created_on)).total_seconds() / 3600
                rows[key] = metric(key, hours, [entry], threshold=thresholds.get(key))
            else:
                rows[key].update(status="not_applicable", reason="هنوز به این مرحله نرسیده؛ زمان تا اولین ورود محاسبه می‌شود.")
        reopens = sum(a["kind"] in {"closed", "resolved"} and b["kind"] not in {"closed", "resolved"}
                      for a, b in zip(intervals, intervals[1:]))
        rows["reopens"] = metric("reopens", reopens, intervals, threshold=thresholds.get("reopens"))
        rows["reopens"]["unit"] = "بار"
    else:
        for key, (_, source) in METRICS.items():
            if source == "status_history":
                rows[key]["reason"] = history_error
    created = utc_naive(case.created_on)
    if getattr(case, "responsibility_history_complete", False):
        history = getattr(case, "responsibility_history", [])
        dates = [utc_naive(event.get("entered_at")) for event in history]
        if (history and created and at and dates[0] == created and all(date and date <= at for date in dates)
                and all(left < right for left, right in zip(dates, dates[1:]))
                and all(event.get("owner_id") for event in history)):
            changes = sum(left["owner_id"] != right["owner_id"] for left, right in zip(history, history[1:]))
            rows["owner_changes"] = metric("owner_changes", changes, history, threshold=thresholds.get("owner_changes"))
    # Note creation with staff actor is an internal documentation event,
    # not proof of a response delivered to the customer.
    events = [(utc_naive(getattr(n, "created_on", None)), {"note_id": n.note_id}) for n in case.notes
              if n.note_author and not n.is_customer_authored]
    events += [(utc_naive(t.actual_start), {"task_id": t.task_id}) for t in case.tasks]
    events = [(date, ref) for date, ref in events if date and created and at and created <= date <= at]
    if events:
        first, ref = min(events, key=lambda x: x[0])
        rows["internal_first_action"] = metric("internal_first_action", (first - created).total_seconds() / 3600, [ref], threshold=thresholds.get("internal_first_action"))
    responses = [(utc_naive(getattr(n, "created_on", None)), {"note_id": n.note_id}) for n in case.notes if getattr(n, "is_customer_response", None) is True]
    responses = [(date, ref) for date, ref in responses if date and created and at and created <= date <= at]
    if responses:
        first, ref = min(responses, key=lambda x: x[0])
        rows["customer_first_response"] = metric("customer_first_response", (first - created).total_seconds() / 3600, [ref], threshold=thresholds.get("customer_first_response"))
    deadlines = task_deadlines(case, at)
    eligible = [row for row in deadlines if row["state"] in {"completed", "open_overdue"}]
    if eligible:
        rows["task_deadlines"] = metric("task_deadlines", max(r["delay_hours"] for r in eligible), deadlines, threshold=thresholds.get("task_deadlines"))
        rows["task_deadlines"].update(eligible=len(eligible), total=len(deadlines), late=sum(r["delay_hours"] > 0 for r in eligible))
    # Inactivity requires a complete activity feed and authoritative open state.
    if getattr(case, "data_complete", False) and intervals and intervals[-1]["kind"] not in {"closed", "resolved"}:
        last = max((date for date, _ in events), default=created)
        if last and at:
            rows["inactivity"] = metric("inactivity", (at-last).total_seconds()/3600, [ref for _, ref in events], threshold=thresholds.get("inactivity"))
    return {"case_key": case.case_key, "case_number": case.case_number, "customer": case.customer,
            "owner": case.owner, "status": case.status, "service": case.service,
            "evaluation_at": evaluation_at, "criteria_version": SCHEMA_VERSION,
            "criteria": list(rows.values())}


def management_queue(evaluations):
    return [{**{k: case[k] for k in ("case_key", "case_number", "customer", "owner", "status", "service")},
             "criterion": item, "action": "بررسی شواهد و تعیین اقدام اصلاحی" if item["status"] == "needs_correction" else "تکمیل داده و بررسی دسترسی CRM"}
            for case in evaluations for item in case["criteria"]
            if item["status"] in {"needs_correction", "insufficient_data"}]


def population_summary(cases, evaluations, evaluation_at):
    """A selected-view population, never the entire organisation."""
    at = utc_naive(evaluation_at)
    statuses = Counter((case.status or "نامشخص") for case in cases.values())
    ages = []
    for case in cases.values():
        if (case.status or "").strip().casefold() in {"active", "open", "فعال", "باز"}:
            created = utc_naive(case.created_on)
            if created and at and created <= at:
                ages.append((at-created).total_seconds()/3600)
    durations = [item["value"] for case in evaluations for item in case["criteria"]
                 if item["id"] == "created_to_resolved" and item["value"] is not None]
    ordered = sorted(durations)
    if ordered:
        position = (len(ordered)-1)*0.9
        low = int(position)
        high = min(low+1, len(ordered)-1)
        percentile = ordered[low] + (ordered[high]-ordered[low])*(position-low)
    else:
        percentile = None
    return {"scope": "موارد منتخب از View", "total_selected": len(cases),
            "status_distribution": dict(statuses), "open_age_hours": sorted(ages),
            "open_age_eligible": len(ages), "resolution_eligible": len(durations),
            "resolution_denominator": len(cases), "resolution_median_hours": median(durations) if durations else None,
            "resolution_p90_hours": percentile, "unit": "ساعت تقویمی"}
