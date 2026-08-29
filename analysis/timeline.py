from __future__ import annotations

from analysis.rules import PORTAL_AUTHORS
from data.cleaner import CaseBundle


def build_timeline(case: CaseBundle) -> list[dict]:
    events = []
    for kind, when, obj in case.ai_events_sorted:
        if kind == "note":
            author = (obj.note_author or "نامشخص").strip()
            role = "مشتری/پرتال" if author.casefold() in PORTAL_AUTHORS else "کارشناس"
            events.append({
                "type": "note",
                "date": when.isoformat() if when else None,
                "role": role,
                "author": author,
                "text": obj.description or "(Note خالی)",
                "record_id": obj.note_id,
            })
        else:
            events.append({
                "type": "task",
                "date": when.isoformat() if when else None,
                "role": "کارشناس",
                "author": obj.created_by or "نامشخص",
                "text": obj.description or obj.subject or "(Task بدون شرح)",
                "record_id": obj.task_id,
                "status_reason": obj.status_reason,
            })
    return events
