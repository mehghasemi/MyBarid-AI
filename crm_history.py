"""Conservative reconstruction of authoritative Dynamics audit events."""
from analysis.timing import utc_naive


def reconstruct_history(record, details, status_mapping=None):
    mapping = status_mapping or {}
    created = utc_naive(record.get("createdon"))
    events = []
    for detail in details:
        audit = detail.get("AuditRecord") or {}
        when = utc_naive(audit.get("createdon"))
        if not when:
            return {"history_complete": False, "reason": "زمان معتبر برای همه رکوردهای Audit موجود نیست."}
        events.append((when, str(audit.get("auditid", "")), audit, detail))
    events.sort(key=lambda event: (event[0], event[1]))
    if not created or not any(event[2].get("operation") == 1 and event[0] == created for event in events):
        return {"history_complete": False, "reason": "Audit ایجاد مورد موجود نیست یا تاریخ آن با createdon همخوان نیست."}
    current = {key: record.get(key) for key in ("statecode", "statuscode", "_ownerid_value")}
    initial = dict(current)
    for _, _, audit, detail in reversed(events):
        if audit.get("operation") == 1:
            continue
        old, new = detail.get("OldValue") or {}, detail.get("NewValue") or {}
        for key in current:
            if key in new:
                if key not in old:
                    return {"history_complete": False, "reason": "مقدار قبلی تغییر وضعیت یا مالک در Audit موجود نیست."}
                if initial[key] != new[key]:
                    return {"history_complete": False, "reason": "زنجیره Audit با وضعیت فعلی همخوان نیست؛ احتمال حذف یا Audit غیرفعال وجود دارد."}
                initial[key] = old[key]
    def status_event(values, when, identifier):
        custom = mapping.get(str(values["statuscode"]))
        if isinstance(custom, dict):
            kind, label = custom.get("kind"), custom.get("name")
        else:
            kind = {0: "open", 1: "resolved", 2: "closed"}.get(values["statecode"])
            label = f"وضعیت {values['statuscode']}"
        return {"entered_at": when.isoformat(), "event_id": identifier,
                "status": label, "kind": kind, "status_code": values["statuscode"]}
    history = [status_event(initial, created, "creation")]
    owners = [{"entered_at": created.isoformat(), "owner_id": initial["_ownerid_value"], "event_id": "creation"}]
    values = dict(initial)
    for when, identifier, audit, detail in events:
        new = detail.get("NewValue") or {}
        old = dict(values)
        for key in values:
            if key in new:
                values[key] = new[key]
        if (values["statecode"], values["statuscode"]) != (old["statecode"], old["statuscode"]):
            history.append(status_event(values, when, identifier))
        if values["_ownerid_value"] != old["_ownerid_value"]:
            owners.append({"entered_at": when.isoformat(), "owner_id": values["_ownerid_value"], "event_id": identifier})
    if values != current or any(event["kind"] is None for event in history):
        return {"history_complete": False, "reason": "وضعیت ناشناخته یا زنجیره نامعتبر است؛ نگاشت ادمین لازم است."}
    return {"history_complete": True, "status_history": history,
            "responsibility_history_complete": all(event["owner_id"] for event in owners),
            "responsibility_history": owners,
            "reason": "زنجیره کامل از Audit ایجاد تا وضعیت فعلی اعتبارسنجی شد."}
