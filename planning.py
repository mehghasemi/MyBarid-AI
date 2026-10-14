"""Independent case-planning source, settings, cursor and asynchronous refresh."""
import hashlib
import json
import threading
import time
from datetime import datetime, timezone, timedelta
from uuid import UUID

from database import db
from crm_client import DynamicsCRMClient, dataset_to_payload


def source_key(settings):
    identity = {key: settings.get(key) for key in ("base_url", "organization", "api_version", "view_id", "view_kind")}
    return "planning:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def merge_payload(previous, incoming):
    merged, changed = {}, {}
    for kind, identifier in (("notes", "note_id"), ("tasks", "task_id")):
        rows = {str(row[identifier]): row for row in previous.get(kind, []) if row.get(identifier)}
        count = 0
        for row in incoming.get(kind, []):
            key = row.get(identifier)
            if not key:
                continue
            key = str(key)
            if rows.get(key) != row:
                rows[key] = row
                count += 1
        merged[kind] = list(rows.values())
        changed[kind] = count
    if 'planning_crm' in previous or 'planning_crm' in incoming:
        before, after = previous.get('planning_crm', {}), incoming.get('planning_crm', {})
        merged['planning_crm'] = {**before, **after}
        for key in ('cases', 'programs', 'events'):
            merged['planning_crm'][key] = {**before.get(key, {}), **after.get(key, {})}
        # Absence from an incremental batch is NOT proof of removal from View.
        if after.get('scope_complete'):
            merged['planning_crm']['current_case_ids'] = list(after.get('cases', {}))
            merged['planning_crm']['scope_checked'] = True
        elif 'current_case_ids' in before:
            merged['planning_crm']['current_case_ids'] = list(set(before['current_case_ids']) | set(after.get('cases', {})))
            merged['planning_crm']['scope_checked'] = False
    merged['case_evidence'] = {**previous.get('case_evidence', {}), **incoming.get('case_evidence', {})}
    return merged, changed


class PlanningApiMixin:
    def get_planning_settings(self):
        settings = db.get_setting("planning_crm_settings", {}) or {}
        inherited = self.get_crm_settings()
        connection = {key: inherited[key] for key in ("base_url", "organization", "api_version")}
        snapshot = db.get_latest_crm_snapshot(source_key({**settings, **connection})) if settings.get("view_id") else None
        return {"ok": True, **connection, "view_id": settings.get("view_id", ""),
                "view_kind": settings.get("view_kind", ""), "view_name": settings.get("view_name", ""),
                "last_updated": (snapshot or {}).get("fetched_at"),
                "counts": {key: len((snapshot or {}).get("payload", {}).get(key, [])) for key in ("notes", "tasks")}}

    def _planning_client(self, settings, credentials):
        return DynamicsCRMClient(**{key: settings.get(key, "") for key in
            ("base_url", "organization", "api_version", "view_name", "view_id", "view_kind")},
            username=str(credentials.get("username") or ""), password=str(credentials.get("password") or ""))

    def get_planning_views(self, payload=None):
        payload = payload or {}
        settings = self.get_planning_settings()
        try:
            # Listing never changes the saved default.
            return {"ok": True, "views": self._planning_client(settings, payload).list_note_views()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_planning_settings(self, payload):
        with self._lock:
            if getattr(self, "_planning_status", {}).get("running"):
                return {"ok": False, "error": "تا پایان دریافت، View را تغییر ندهید."}
            try:
                UUID(str(payload.get("view_id", "")))
                if payload.get("view_kind") not in {"userqueries", "savedqueries"} or not str(payload.get("view_name", "")).strip():
                    raise ValueError()
            except (ValueError, TypeError):
                return {"ok": False, "error": "یک View معتبر از فهرست انتخاب کنید."}
            current = self.get_planning_settings()
            settings = {key: str(payload.get(key, current.get(key, ""))).strip() for key in
                        ("view_id", "view_kind", "view_name")}
            settings.update({key: current[key] for key in ("base_url", "organization", "api_version")})
            db.set_setting("planning_crm_settings", settings)
            return {"ok": True, "message": "View پیش‌فرض برنامه‌ریزی ذخیره شد و خودکار تغییر نمی‌کند."}

    def get_planning_sync_status(self):
        with self._lock:
            status = dict(getattr(self, "_planning_status", {"running": False, "stage": "آماده دریافت"}))
        if status.get("started_at"):
            status["elapsed_seconds"] = round(time.time() - status["started_at"] if status.get("running")
                                               else status.get("elapsed_seconds", 0))
        return status

    def sync_planning_view(self, payload=None):
        settings = self.get_planning_settings()
        if not settings["view_id"]:
            return {"ok": False, "error": "ابتدا View پیش‌فرض برنامه‌ریزی را انتخاب و ذخیره کنید."}
        with self._lock:
            if getattr(self, "_planning_status", {}).get("running"):
                return {"ok": False, "error": "دریافت برنامه‌ریزی در حال اجراست."}
            self._planning_status = {"running": True, "done": False, "error": None,
                                     "stage": "شروع دریافت", "started_at": time.time()}
        threading.Thread(target=self._planning_worker, args=(settings, payload or {}), daemon=True).start()
        return {"ok": True}

    def _planning_worker(self, settings, credentials):
        started = datetime.now(timezone.utc).replace(tzinfo=None)
        source = source_key(settings)
        def progress(stage, completed=0, total=0, detail=""):
            with self._lock:
                self._planning_status.update(stage=stage, completed=completed, total=total, detail=detail)
        try:
            previous = db.get_latest_crm_snapshot(source)
            cursor = (previous or {}).get("metadata", {}).get("cursor")
            since = datetime.fromisoformat(cursor) - timedelta(seconds=1) if cursor else None
            context = (previous or {}).get('payload', {}).get('planning_crm')
            # One initial context backfill for old snapshots, not a periodic full re-fetch.
            if context is None:
                since = None
            dataset, metadata = self._planning_client(settings, credentials).fetch_view_dataset(
                since=since, activity_since=since, include_related_activities=False, progress_callback=progress,
                planning_previous=context or {})
            incoming = dataset_to_payload(dataset)
            if 'planning_context' in metadata:
                incoming['planning_crm'] = metadata.pop('planning_context')
            payload, changed = merge_payload((previous or {}).get("payload", {}), incoming)
            metadata.update(cursor=started.isoformat(), view_id=settings["view_id"],
                            view_kind=settings["view_kind"], changed=changed)
            db.save_crm_snapshot(source, settings["view_name"], metadata["fetched_at"], metadata, payload)
            with self._lock:
                self._planning_status.update(running=False, done=True, stage="دریافت کامل شد", changed=changed,
                    counts={key: len(payload[key]) for key in ("notes", "tasks")},
                    mode="incremental" if since else "initial", elapsed_seconds=time.time()-self._planning_status["started_at"])
        except Exception as exc:
            with self._lock:
                self._planning_status.update(running=False, done=False, error=str(exc), stage="دریافت ناموفق بود",
                                             elapsed_seconds=time.time()-self._planning_status["started_at"])
        # Evaluation dataset/result and its settings are never modified here.
