"""Paginated local CRM inventory for each module (no external calls)."""
from database import db
from planning import source_key


def cached_module_data(api, module, page=0, search=""):
    if module not in {"crm-quality", "case-planning"}:
        return {"ok": False, "error": "ماژول معتبر نیست."}
    try:
        page = max(0, int(page))
    except (ValueError, TypeError):
        return {"ok": False, "error": "صفحه معتبر نیست."}
    settings = api.get_crm_settings() if module == "crm-quality" else api.get_planning_settings()
    source = "dynamics365" if module == "crm-quality" else source_key(settings)
    snapshot = db.get_latest_crm_snapshot(source) if module == "crm-quality" or settings.get("view_id") else None
    if not snapshot:
        return {"ok": True, "loaded": False, "selected_view": settings.get("view_name", ""),
                "rows": [], "total": 0, "page": 0, "page_size": 25}
    payload = snapshot.get("payload") or {}
    groups = {}
    for kind in ("notes", "tasks"):
        for record in payload.get(kind, []):
            key = str(record.get("case_number") or record.get("case_id") or record.get("case_title") or
                      'unlinked:' + str(record.get("note_id") or record.get("task_id") or len(groups)))
            case = groups.setdefault(key, {"key": key, "number": record.get("case_number") or "—",
                "title": "", "status": "", "customer": "", "owner": "", "service": "", "notes": [], "tasks": []})
            case["title"] = case["title"] or record.get("case_title") or record.get("regarding") or ""
            case["status"] = case["status"] or record.get("case_status") or ""
            for field in ("customer", "owner", "service"):
                case[field] = case[field] or record.get(field) or ""
            case[kind].append({"id": record.get("note_id") or record.get("task_id"),
                "title": record.get("subject") or "", "text": record.get("note_text") or record.get("description") or "",
                "date": record.get("note_date") or record.get("created_on"),
                "modified_on": record.get("modified_on")})
    cases = sorted(groups.values(), key=lambda row: row['key'])
    query = str(search or "").strip().casefold()
    filtered = [row for row in cases if not query or query in (row['number'] + ' ' + row['title']).casefold()]
    total = len(filtered)
    page = min(page, max(0, (total - 1) // 25))
    meta = snapshot.get("metadata") or {}
    selected = settings.get("view_name", "")
    return {"ok": True, "loaded": True, "selected_view": selected, "snapshot_view": snapshot['view_name'],
        "view_mismatch": selected != snapshot['view_name'], "fetched_at": snapshot['fetched_at'],
        "counts": {"cases": len(cases), "notes": len(payload.get('notes', [])), "tasks": len(payload.get('tasks', []))},
        "sync_mode": meta.get('sync_mode'), "changed": meta.get('changed'), "cursor": meta.get('cursor'),
        "sync_count": meta.get('sync_count'), "last_full_sync_at": meta.get('last_full_sync_at'),
        "new_or_changed_notes": meta.get('new_or_changed_notes'), "deleted_notes": meta.get('deleted_notes'),
        "related_activities": meta.get('related_activities'),
        "rows": filtered[page * 25:(page + 1) * 25], "total": total, "page": page, "page_size": 25}
