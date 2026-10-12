from __future__ import annotations

import json
import copy
import hashlib
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ai.providers import AISettings
from ai.analyzer import AnalysisCancelled, analyze_case, is_case_ai_analyzed, _case_signature
from analysis.timeline import build_timeline
from analysis.suspicious import normalized_rule_settings, SUSPICIOUS_RULE_INFO
from analysis.rule_settings import normalize_analysis_rules, DEFAULT_ANALYSIS_RULES, RULE_SETTING_INFO
from config.criteria_config import Category, Criterion, CriteriaConfig, load_criteria_config, save_criteria_config
import webview
from database import db
from crm_client import (
    DEFAULT_API_VERSION, DEFAULT_BASE_URL, DEFAULT_ORGANIZATION, DEFAULT_VIEW_NAME,
    CRMClientError, DynamicsCRMClient, dataset_from_payload, dataset_to_payload,
)
from pipeline import Dataset, run_general_analysis
from analysis.scoring import score_case
import pipeline as pipeline_mod
from reports.csv_export import export_csv
from reports.employee_report_export import export_expert_report_excel as export_expert_report_excel_file
from reports.excel_export import export_excel

USER_CONFIG_PATH = db.app_data_dir() / "criteria_config.json"
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
CHANGELOG_FILE = Path(__file__).resolve().parent / "CHANGELOG.json"
CURRENT_CRITERIA_CATEGORIES = {
    "correct_diagnosis_action",
    "customer_outcome_contribution",
    "responsiveness",
    "ownership_followup",
    "documentation_sufficiency",
    "data_quality",
}
CRM_FULL_RECONCILIATION_INTERVAL_SECONDS = 7 * 24 * 60 * 60


def get_app_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "0.0.0"


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else None


def _dataset_id(snapshot: dict | None) -> str | None:
    """Return a stable identity for the locally persisted CRM Snapshot."""
    if not snapshot or not snapshot.get("payload"):
        return None
    payload = copy.deepcopy(snapshot["payload"])
    for key in ("notes", "tasks"):
        if isinstance(payload.get(key), list):
            payload[key] = sorted(
                payload[key],
                key=lambda row: str(row.get("note_id") or row.get("task_id") or ""),
            )
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()




class Api:
    def get_management_evaluation(self) -> dict:
        if not self.result or "quantitative" not in self.result:
            return {"ok": False, "error": "برای این Snapshot هنوز ارزیابی با نسخه جدید معیارها اجرا نشده است."}
        return {"ok": True, "evaluation_at": self.result.get("evaluation_at"),
                "criteria_version": "3.0", "scope": "فقط موارد منتخب از View؛ آمار کل سازمان نیست",
                "cases": self.result["quantitative"], "queue": self.result["management_queue"],
                "summary": self.result.get("management_summary", {}),
                "catalog": self.result.get("criterion_catalog", []),
                "severity_settings": db.get_setting("management_severities", {}),
                "status_mapping": db.get_setting("crm_status_mapping", {}),
                "thresholds": db.get_setting("management_thresholds", {}), "actions": db.get_management_actions(),
                "attribution_notice": self.result.get("attribution_notice")}

    def save_management_thresholds(self, thresholds: dict) -> dict:
        from analysis.management import METRICS
        import math
        if not isinstance(thresholds, dict):
            return {"ok": False, "error": "ساختار حدنصاب‌ها معتبر نیست."}
        checked = {}
        for key, value in thresholds.items():
            if key not in METRICS:
                return {"ok": False, "error": "معیار ناشناخته است."}
            if value is None or value == "":
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                return {"ok": False, "error": "حدنصاب باید عدد نامنفی باشد."}
            if not math.isfinite(number) or number < 0:
                return {"ok": False, "error": "حدنصاب باید عدد نامنفی و محدود باشد."}
            checked[key] = number
        db.set_setting("management_thresholds", checked)
        return {"ok": True, "message": "حدنصاب‌ها ذخیره شد؛ از ارزیابی بعدی اعمال می‌شود."}

    def save_management_severities(self, values: dict) -> dict:
        from config.criterion_catalog import criterion_catalog
        allowed = {item["id"] for item in criterion_catalog(self.config)}
        if not isinstance(values, dict) or any(key not in allowed or value not in {"info", "warning", "critical"}
                                             for key, value in values.items()):
            return {"ok": False, "error": "شناسه معیار یا شدت معتبر نیست."}
        db.set_setting("management_severities", values)
        return {"ok": True, "message": "شدت معیارها ذخیره شد؛ از ارزیابی بعدی اعمال می‌شود."}

    def record_management_action(self, case_key: str, criterion_id: str, decision: str,
                                 responsible: str, due_at: str) -> dict:
        if not self.result or not any(row["case_key"] == case_key and row["criterion"]["id"] == criterion_id
                                       for row in self.result.get("management_queue", [])):
            return {"ok": False, "error": "مورد و معیار باید در صف بررسی موجود باشند."}
        if not decision.strip() or not responsible.strip():
            return {"ok": False, "error": "شرح تصمیم و مسئول اقدام الزامی است."}
        try:
            datetime.fromisoformat(due_at)
        except (ValueError, TypeError):
            return {"ok": False, "error": "موعد اقدام معتبر نیست."}
        db.save_management_action(case_key, criterion_id, decision.strip(), responsible.strip(), due_at,
                                  self.result.get("evaluation_at"))
        return {"ok": True}

    def __init__(self):
        self.window = None
        self.dataset: Dataset | None = None
        self.config: CriteriaConfig = self._load_config()
        self.ai_settings: AISettings = self._load_ai_settings()
        self.suspicious_rules = normalized_rule_settings(db.get_setting("suspicious_rules", {}))
        self.analysis_rules = normalize_analysis_rules(db.get_setting("analysis_rules", {}))
        self.result: dict | None = None
        self.status = {"running": False, "done": False, "stage": "", "current": 0, "total": 0, "error": None}
        self._analysis_generation = 0
        self._analysis_cancel_event: threading.Event | None = None
        self._case_ai_status: dict[str, dict] = {}
        self._crm_sync_status = {
            "running": False, "done": False, "error": None,
            "stage": "", "result": None, "started_at": None,
            "elapsed_seconds": 0, "events": [], "last_event_at": None,
        }
        self._lock = threading.Lock()
        # Restore the latest local CRM snapshot only. This is deliberately
        # offline: startup must never contact CRM or read Excel automatically.
        try:
            snapshot = db.get_latest_crm_snapshot()
            if snapshot and snapshot.get("payload"):
                self.dataset = dataset_from_payload(snapshot["payload"])
                db.set_setting("data_source", "crm")
                saved = db.get_local_analysis_record()
                snapshot_id = _dataset_id(snapshot)
                if saved and saved.get("result"):
                    self.result = saved["result"]
                    if saved.get("dataset_id_version", 1) < 2 and snapshot_id:
                        db.save_local_analysis(
                            self.result,
                            dataset_id=snapshot_id,
                            view_name=snapshot.get("view_name"),
                        )
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def __dir__(self):
        """Expose only API methods to pywebview's bridge introspection.

        Returning instance state (Dataset, CriteriaConfig, locks, etc.) from
        dir() makes pywebview recursively inspect those object graphs while it
        builds the JavaScript API. On some WebView2/pythonnet combinations
        that recursion reaches Python's limit and the UI remains Not
        Responding before pywebviewready.
        """
        return sorted(
            name for name in dir(type(self))
            if not name.startswith("_") and callable(getattr(type(self), name, None))
        )

    def set_window(self, window):
        self.window = window

    def get_version(self) -> str:
        return get_app_version()

    def get_changelog(self) -> list[dict]:
        if not CHANGELOG_FILE.exists():
            return []
        try:
            payload = json.loads(CHANGELOG_FILE.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    # ------------------------------------------------------------- config --

    def _load_config(self) -> CriteriaConfig:
        if USER_CONFIG_PATH.exists():
            try:
                stored = load_criteria_config(USER_CONFIG_PATH)
                stored_categories = {category.id for category in stored.categories}
                if CURRENT_CRITERIA_CATEGORIES.issubset(stored_categories):
                    return stored
                # Migrate the legacy built-in/user criteria to the current schema once.
                current = load_criteria_config()
                save_criteria_config(current, USER_CONFIG_PATH)
                return current
            except Exception:
                pass
        return load_criteria_config()

    def _load_ai_settings(self) -> AISettings:
        stored = db.get_setting("ai_settings", {}) or {}
        settings = AISettings(**{**asdict(AISettings()), **stored})
        settings.api_key = db.load_api_key()
        if settings.provider == "gemini" and settings.model in {
            "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash",
        }:
            settings.model = "gemini-3.6-flash"
        return settings

    # -------------------------------------------------------------- files --

    def pick_file(self) -> str | None:
        if not self.window:
            return None
        try:
            dialog_type = getattr(getattr(webview, "FileDialog", None), "OPEN", webview.OPEN_DIALOG)
            result = self.window.create_file_dialog(
                dialog_type, file_types=("JSON Settings (*.json)",),
                allow_multiple=False,
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return None
        return result[0] if result else None


    def get_crm_settings(self) -> dict:
        stored = db.get_setting("crm_settings", {}) or {}
        return {
            "base_url": stored.get("base_url", DEFAULT_BASE_URL),
            "organization": stored.get("organization", DEFAULT_ORGANIZATION),
            "api_version": stored.get("api_version", DEFAULT_API_VERSION),
            "view_name": stored.get("view_name") or "",
            "data_source": "crm",
            "last_snapshot": db.get_latest_crm_snapshot(),
        }

    def get_dataset_info(self) -> dict:
        """Return the locally active dataset without reading any external source."""
        if not self.dataset:
            return {"ok": True, "loaded": False, "total_cases": 0, "total_notes": 0, "total_tasks": 0}
        return {
            "ok": True, "loaded": True,
            "source": "crm",
            "total_cases": len(self.dataset.cases),
            "total_notes": len(self.dataset.notes),
            "total_tasks": len(self.dataset.tasks),
        }

    def get_analysis_info(self) -> dict:
        record = db.get_local_analysis_record()
        snapshot = db.get_latest_crm_snapshot()
        current_id = _dataset_id(snapshot)
        saved_id = (record or {}).get("dataset_id")
        stale = bool(
            self.result and saved_id and current_id and saved_id != current_id
        )
        return {
            "ok": True,
            "loaded": bool(self.result),
            "stale": stale,
            "saved_at": (record or {}).get("saved_at"),
        }


    def save_crm_settings(self, payload: dict) -> dict:
        settings = {
            "base_url": str(payload.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
            "organization": str(payload.get("organization") or DEFAULT_ORGANIZATION).strip("/"),
            "api_version": str(payload.get("api_version") or DEFAULT_API_VERSION).strip("/"),
            "view_name": str(payload.get("view_name") or "").strip(),
        }
        db.set_setting("crm_settings", settings)
        return {"ok": True, **settings}

    @staticmethod
    def _crm_client_settings(settings: dict, payload: dict) -> dict:
        return {
            **{key: settings[key] for key in ("base_url", "organization", "api_version", "view_name")},
            "username": str(payload.get("username") or ""),
            "password": str(payload.get("password") or ""),
        }

    def test_crm_connection(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        settings = self.save_crm_settings(payload)
        try:
            result = DynamicsCRMClient(**self._crm_client_settings(settings, payload)).test_connection()
            return {"ok": True, "api_root": result["api_root"]}
        except CRMClientError as exc:
            return {"ok": False, "error": str(exc)}

    def get_crm_views(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        settings = self.save_crm_settings(payload)
        try:
            client = DynamicsCRMClient(**self._crm_client_settings(settings, payload))
            return {"ok": True, "views": client.list_note_views()}
        except CRMClientError as exc:
            return {"ok": False, "views": [], "error": str(exc)}

    def inspect_crm_case_audit(self, case_key: str, payload: dict | None = None) -> dict:
        """Admin-only read-only capability diagnostic; not a fake history feed."""
        if not self.dataset or case_key not in self.dataset.cases:
            return {"ok": False, "error": "مورد باید در Snapshot محلی موجود باشد."}
        case = self.dataset.cases[case_key]
        case_id = next((note.case_id for note in case.notes if note.case_id), None)
        if not case_id:
            return {"ok": False, "error": "شناسه سازمانی CRM برای این مورد در Snapshot موجود نیست."}
        try:
            settings = self.get_crm_settings()
            client = DynamicsCRMClient(**self._crm_client_settings(settings, payload or {}))
            return {"ok": True, **client.read_case_audit(case_id)}
        except CRMClientError as exc:
            return {"ok": False, "error": str(exc)}

    def retrieve_crm_case_history(self, case_key: str, payload: dict | None = None) -> dict:
        """Explicit, on-demand read: no repeated whole-population audit scans."""
        if not self.dataset or case_key not in self.dataset.cases:
            return {"ok": False, "error": "مورد در Snapshot محلی موجود نیست."}
        case = self.dataset.cases[case_key]
        case_id = next((note.case_id for note in case.notes if note.case_id), None)
        if not case_id:
            return {"ok": False, "error": "شناسه CRM این مورد موجود نیست."}
        try:
            settings = self.get_crm_settings()
            client = DynamicsCRMClient(**self._crm_client_settings(settings, payload or {}))
            evidence = client.read_case_history(case_id, db.get_setting("crm_status_mapping", {}))
            if not evidence.get("history_complete"):
                return {"ok": False, "error": evidence["reason"]}
            with self._lock:
                if not self.dataset or self.dataset.cases.get(case_key) is not case:
                    return {"ok": False, "error": "Snapshot هنگام دریافت تغییر کرد؛ مورد را دوباره انتخاب کنید."}
                for key in ("history_complete", "status_history", "responsibility_history_complete", "responsibility_history"):
                    setattr(case, key, evidence[key])
                snapshot = db.get_latest_crm_snapshot()
                if snapshot:
                    db.save_crm_snapshot("dynamics365", snapshot["view_name"], snapshot["fetched_at"],
                                         snapshot.get("metadata", {}), dataset_to_payload(self.dataset))
            return {"ok": True, "message": "تاریخچه معتبر ذخیره شد؛ برای محاسبه معیارهای زمانی ارزیابی را اجرا کنید."}
        except (CRMClientError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def save_crm_status_mapping(self, mapping: dict) -> dict:
        kinds = {"open", "resolved", "closed", "waiting_customer", "waiting_team", "waiting_third_party"}
        if not isinstance(mapping, dict) or any(not str(key).isdigit() or not isinstance(value, dict)
                or value.get("kind") not in kinds or not str(value.get("name", "")).strip()
                for key, value in mapping.items()):
            return {"ok": False, "error": "نگاشت وضعیت معتبر نیست."}
        db.set_setting("crm_status_mapping", mapping)
        return {"ok": True}

    def sync_crm_view(self, payload: dict | None = None) -> dict:
        """Start CRM synchronization without blocking the WebView UI."""
        with self._lock:
            if self._crm_sync_status.get("running"):
                return {"ok": False, "error": "دریافت قبلی CRM هنوز در حال اجراست."}
            self._crm_sync_status = {
                "running": True, "done": False, "error": None,
                "stage": "در حال اتصال به CRM...", "result": None,
                "started_at": time.time(), "elapsed_seconds": 0,
                "events": [], "last_event_at": None,
            }
        thread = threading.Thread(
            target=self._sync_crm_view_worker,
            args=(copy.deepcopy(payload or {}),),
            daemon=True,
        )
        thread.start()
        self._crm_log_event("درخواست همگام‌سازی ثبت شد.")
        return {"ok": True, "started": True}

    def _crm_log_event(self, message: str, level: str = "info") -> None:
        with self._lock:
            now = datetime.now().isoformat(timespec="seconds")
            events = self._crm_sync_status.setdefault("events", [])
            events.append({"at": now, "level": level, "message": str(message)})
            self._crm_sync_status["events"] = events[-80:]
            self._crm_sync_status["last_event_at"] = now

    def get_crm_sync_status(self) -> dict:
        with self._lock:
            status = copy.deepcopy(self._crm_sync_status)
            if status.get("running") and status.get("started_at"):
                status["elapsed_seconds"] = max(
                    0, int(time.time() - status["started_at"])
                )
            return status

    def _sync_crm_view_worker(self, payload: dict) -> None:
        try:
            self._crm_log_event("Worker همگام‌سازی CRM شروع شد.")
            with self._lock:
                self._crm_sync_status.update({
                    "stage": "در حال دریافت View از CRM...", "progress": 0,
                    "progress_completed": 0, "progress_total": 0, "progress_detail": "",
                })
            result = self._perform_crm_sync(payload)
            if isinstance(result, dict) and result.get("ok") is False:
                self._crm_log_event(f"همگام‌سازی ناموفق: {result.get('error') or 'خطای نامشخص'}", "error")
            else:
                self._crm_log_event("فرآیند دریافت و ذخیره‌سازی پایان یافت.")
            with self._lock:
                self._crm_sync_status.update({
                    "running": False,
                    "done": not (isinstance(result, dict) and result.get("ok") is False),
                    "error": result.get("error") if isinstance(result, dict) and result.get("ok") is False else None,
                    "stage": "دریافت اطلاعات کامل شد", "result": result,
                    "elapsed_seconds": int(
                        time.time() - (self._crm_sync_status.get("started_at") or time.time())
                    ),
                })
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._crm_log_event(f"خطای پیش‌بینی‌نشده: {exc}", "error")
            with self._lock:
                self._crm_sync_status.update({
                    "running": False, "done": False,
                    "error": str(exc), "stage": "دریافت CRM ناموفق بود",
                    "result": None,
                    "elapsed_seconds": int(
                        time.time() - (self._crm_sync_status.get("started_at") or time.time())
                    ),
                })

    def _perform_crm_sync(self, payload: dict) -> dict:
        payload = payload or {}
        settings = self.save_crm_settings(payload)
        self._crm_log_event(f"View انتخاب‌شده: {settings.get('view_name')}")
        client = DynamicsCRMClient(**self._crm_client_settings(settings, payload))
        previous = db.get_latest_crm_snapshot()
        previous_meta = (previous or {}).get("metadata") or {}
        previous_payload = (previous or {}).get("payload") or {}
        same_view = bool(previous and previous.get("view_name") == settings["view_name"])
        sync_count = int(previous_meta.get("sync_count") or 0)
        force_full = bool(payload.get("full_sync"))
        previous_watermarks = previous_meta.get("watermarks") or {}
        # Older Snapshots (before v1.9.85) do not have Watermarks. Bootstrap
        # them from the Snapshot timestamp so the first run after upgrade is
        # incremental instead of downloading the whole View again.
        bootstrap_watermark = (
            previous_meta.get("fetched_at")
            or (previous or {}).get("fetched_at")
        )
        view_entity = str(
            previous_meta.get("view_entity_type")
            or ("incident" if previous_meta.get("related_activities") else "annotation")
        ).casefold()
        case_watermark = (
            previous_watermarks.get("incident")
            or previous_meta.get("max_case_modified_on")
            or bootstrap_watermark
        )
        activity_watermark = (
            previous_watermarks.get("activity")
            or previous_meta.get("max_note_modified_on")
            or bootstrap_watermark
        )
        if view_entity != "incident":
            case_watermark = (
                previous_watermarks.get(view_entity)
                or previous_meta.get("max_modified_on")
                or bootstrap_watermark
            )
        last_full_at = previous_meta.get("last_full_sync_at") or bootstrap_watermark
        full_reconcile_due = True
        if last_full_at:
            try:
                full_reconcile_due = (
                    datetime.now() - datetime.fromisoformat(last_full_at)
                ).total_seconds() >= CRM_FULL_RECONCILIATION_INTERVAL_SECONDS
            except ValueError:
                full_reconcile_due = True
        # Deleted records are not returned by a modifiedon query. Reconcile
        # periodically, while keeping normal refreshes incremental.
        incremental = (
            same_view and not force_full
            and case_watermark
            and not full_reconcile_due
        )
        since = datetime.fromisoformat(case_watermark) if incremental and case_watermark else None
        activity_since = (
            datetime.fromisoformat(activity_watermark)
            if incremental and activity_watermark else None
        )
        with self._lock:
            self._crm_sync_status.update({
                "sync_mode": "incremental" if incremental else "full",
                "stage": "در حال آماده‌سازی همگام‌سازی افزایشی..." if incremental else "در حال آماده‌سازی همگام‌سازی کامل...",
                "progress": 2,
                "progress_detail": "بررسی View و زمان آخرین دریافت",
            })
        def report_progress(stage, completed=0, total=0, detail=""):
            event_message = stage + (f" — {detail}" if detail else "")
            with self._lock:
                previous_message = self._crm_sync_status.get("last_progress_message")
                self._crm_sync_status.update({
                    "stage": stage,
                    "progress": round((completed / total) * 100) if total else 0,
                    "progress_completed": completed,
                    "progress_total": total,
                    "progress_detail": detail,
                    "last_progress_message": event_message,
                })
            if event_message != previous_message:
                self._crm_log_event(event_message)
        try:
            dataset, metadata = client.fetch_view_dataset(
                since=since,
                activity_since=activity_since,
                include_related_activities=bool(payload.get("include_related_activities")),
                progress_callback=report_progress,
            )
        except CRMClientError as exc:
            self._crm_log_event(f"خطای CRM: {exc}", "error")
            return {"ok": False, "error": str(exc)}
        previous_notes = {
            str(row.get("note_id")): row for row in
            previous_payload.get("notes", [])
            if row.get("note_id")
        }
        previous_tasks = {
            str(row.get("task_id")): row for row in
            previous_payload.get("tasks", [])
            if row.get("task_id")
        }
        fetched_payload = dataset_to_payload(dataset)
        fetched_notes = {
            str(row.get("note_id")): row for row in fetched_payload.get("notes", [])
            if row.get("note_id")
        }
        fetched_tasks = {
            str(row.get("task_id")): row for row in
            fetched_payload.get("tasks", [])
            if row.get("task_id")
        }
        if incremental:
            merged_notes = dict(previous_notes)
            merged_notes.update(fetched_notes)
            merged_tasks = dict(previous_tasks)
            merged_tasks.update(fetched_tasks)
            current_payload = {
                "notes": list(merged_notes.values()),
                "tasks": list(merged_tasks.values()),
                # Incoming evidence overrides only cases actually refreshed.
                # Retained histories are marked incomplete until reconfirmed.
                "case_evidence": {
                    **{key: {**value, "history_complete": False,
                             "responsibility_history_complete": False, "data_complete": False}
                       for key, value in previous_payload.get("case_evidence", {}).items()},
                    **fetched_payload.get("case_evidence", {}),
                },
            }
            dataset = dataset_from_payload(current_payload)
        else:
            current_payload = fetched_payload
        current_notes = {
            str(row.get("note_id")): row for row in current_payload.get("notes", [])
            if row.get("note_id")
        }
        changed_keys = [
            key for key, row in current_notes.items()
            if key not in previous_notes or row != previous_notes[key]
        ]
        metadata.update({
            "new_or_changed_notes": len(changed_keys),
            "unchanged_notes": max(0, len(current_notes) - len(changed_keys)),
            "deleted_notes": (
                len(set(previous_notes) - set(current_notes))
                if not incremental else 0
            ),
            "sync_count": sync_count + 1,
            "last_full_sync_at": (
                metadata["fetched_at"] if not incremental
                else previous_meta.get("last_full_sync_at")
            ),
            "watermarks": {
                "incident": metadata.get("max_case_modified_on") or case_watermark,
                "activity": metadata.get("max_note_modified_on") or activity_watermark,
                "annotation": metadata.get("max_note_modified_on") or activity_watermark,
                "task": metadata.get("max_task_modified_on") or activity_watermark,
            },
        })
        db.save_crm_snapshot("dynamics365", settings["view_name"], metadata["fetched_at"],
                             metadata, current_payload)
        db.set_setting("data_source", "crm")
        current_id = _dataset_id({
            "view_name": settings["view_name"],
            "payload": current_payload,
        })
        previous_analysis = db.get_local_analysis_record()
        with self._lock:
            self._analysis_generation += 1
            self.dataset = dataset
            # Keep the previous result available even when the Snapshot
            # changed. The UI marks it as stale, while the user can still
            # inspect the previous report and explicitly run a new analysis.
            self.result = previous_analysis.get("result") if previous_analysis else None
        return {
            "ok": True, "source": "CRM", "view_name": settings["view_name"],
            "fetched_at": metadata["fetched_at"], "total_cases": len(dataset.cases),
            "total_notes": len(dataset.notes), "total_tasks": len(dataset.tasks),
            "date_bounds": self._dataset_date_bounds(dataset),
            "new_or_changed_notes": metadata["new_or_changed_notes"],
            "unchanged_notes": metadata["unchanged_notes"],
            "deleted_notes": metadata["deleted_notes"],
            "sync_mode": metadata.get("sync_mode", "full"),
            "warning": (
                "Note و Taskهای وابسته دریافت شدند."
                if metadata.get("related_activities")
                else "برای سرعت، فقط رکوردهای View دریافت شدند؛ دریافت Note و Taskهای وابسته اختیاری است."
            ),
        }

    @staticmethod
    def _dataset_date_bounds(dataset: Dataset) -> dict:
        dates = [n.note_date for n in dataset.notes if n.note_date]
        return {"min": _iso(min(dates)), "max": _iso(max(dates))} if dates else {"min": None, "max": None}

    def get_dataset_case_keys(self) -> dict:
        return {"ok": True, "keys": sorted(self.dataset.cases) if self.dataset else []}

    def get_dataset_cases(self, query: str = "", page: int = 0, page_size: int = 50) -> dict:
        if not self.dataset:
            return {"ok": False, "rows": [], "total": 0}
        query = (query or "").strip().casefold()
        rows = []
        for key, case in self.dataset.cases.items():
            searchable = " ".join([
                str(key), str(case.case_number or ""), str(case.case_title or ""),
                str(case.service or ""), str(case.owner or ""), str(case.status or ""),
            ]).casefold()
            if query and query not in searchable:
                continue
            rows.append({
                "case_key": key,
                "case_number": case.case_number,
                "case_title": case.case_title,
                "service": case.service,
                "owner": case.owner,
                "status": case.status,
                "status_reason": case.status_reason,
                "notes": len(case.notes),
                "tasks": len(case.tasks),
            })
        rows.sort(key=lambda row: (str(row["case_number"] or row["case_key"])))
        total = len(rows)
        page = max(0, int(page or 0))
        page_size = max(1, min(200, int(page_size or 50)))
        start = page * page_size
        return {"ok": True, "rows": rows[start:start + page_size], "total": total,
                "page": page, "page_size": page_size}


    def pick_save_path(self, suggested_name: str) -> str | None:
        if not self.window:
            return None
        try:
            dialog_type = getattr(getattr(webview, "FileDialog", None), "SAVE", webview.SAVE_DIALOG)
            result = self.window.create_file_dialog(
                dialog_type, save_filename=suggested_name
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return None
        return result if isinstance(result, str) else (result[0] if result else None)


    def clear_dataset(self) -> dict:
        with self._lock:
            self._analysis_generation += 1
            self.dataset = None
            self.result = None
            db.clear_local_analysis()
            if self._analysis_cancel_event:
                self._analysis_cancel_event.set()
            self.status = {"running": False, "done": False, "cancelled": False, "stage": "", "current": 0, "total": 0, "error": None}
        return {"ok": True}

    # -------------------------------------------------------- expert groups

    DEFAULT_GROUP_TEMPLATES = {
        "Help Desk": {
            "review_unit": "case",
            "names": ["مرندی", "حدادی", "جلالی", "فتحعلی", "مهدوی‌نیا", "امیر حسین فیض"],
        },
        "پشتیبانی فنی": {
            "review_unit": "task",
            "names": ["بندلو", "نورمحمدی", "کتاب‌الهی", "محمد حسن فتوحی", "قاسم آزادهو", "علی روایی", "حامد عابدی"],
        },
    }

    def get_detected_experts(self) -> dict:
        if not self.dataset:
            return {"ok": False, "experts": []}
        from analysis.experts import primary_expert
        case_experts = {primary_expert(c) for c in self.dataset.cases.values()}
        task_experts = {t.created_by for t in self.dataset.tasks if t.created_by}
        experts = sorted(case_experts | task_experts)
        return {"ok": True, "experts": experts}

    def get_expert_groups(self) -> dict:
        groups = db.get_setting("expert_groups", {}) or {}
        # سازگاری با قالب قدیمی (فقط لیست کارشناسان، بدون review_unit)
        normalized = {}
        for name, value in groups.items():
            if isinstance(value, list):
                normalized[name] = {"experts": value, "review_unit": "case"}
            else:
                normalized[name] = value
        return {"ok": True, "groups": normalized}

    def save_expert_group(self, name: str, experts: list[str], review_unit: str = "case") -> dict:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "نام گروه نمی‌تواند خالی باشد."}
        if not experts:
            return {"ok": False, "error": "حداقل یک کارشناس باید انتخاب شود."}
        if review_unit not in ("case", "task"):
            return {"ok": False, "error": "واحد بررسی نامعتبر است."}
        groups = db.get_setting("expert_groups", {}) or {}
        groups[name] = {"experts": experts, "review_unit": review_unit}
        db.set_setting("expert_groups", groups)
        return {"ok": True}

    def delete_expert_group(self, name: str) -> dict:
        groups = db.get_setting("expert_groups", {}) or {}
        groups.pop(name, None)
        db.set_setting("expert_groups", groups)
        return {"ok": True}

    @staticmethod
    def _normalize_name(text: str) -> str:
        return "".join((text or "").split()).replace("\u200c", "").casefold()

    def suggest_default_groups(self) -> dict:
        """پیشنهاد اعضای دو گروه پیش‌فرض (Help Desk / پشتیبانی فنی) بر اساس
        تطبیق تقریبی نام‌های داده‌شده با نام کامل کارشناسان شناسایی‌شده در
        داده واقعی. چیزی ذخیره نمی‌شود؛ فقط برای تأیید کاربر برگردانده می‌شود."""
        if not self.dataset:
            return {"ok": False, "error": "ابتدا فایل‌ها را بارگذاری کنید."}
        detected = self.get_detected_experts()["experts"]
        norm_map = {self._normalize_name(e): e for e in detected}

        result = {}
        for group_name, tmpl in self.DEFAULT_GROUP_TEMPLATES.items():
            entries = []
            for target in tmpl["names"]:
                target_norm = self._normalize_name(target)
                matches = [full for norm, full in norm_map.items() if target_norm in norm or norm in target_norm]
                matches = sorted(set(matches))
                entries.append({
                    "target": target,
                    "matches": matches,
                    "status": "matched" if len(matches) == 1 else ("ambiguous" if len(matches) > 1 else "not_found"),
                })
            result[group_name] = {"review_unit": tmpl["review_unit"], "entries": entries}
        return {"ok": True, "suggestions": result}

    def create_default_groups(self, selections: dict) -> dict:
        """selections: { group_name: {"review_unit": "...", "experts": [نام‌های نهایی تأییدشده]} }"""
        groups = db.get_setting("expert_groups", {}) or {}
        created = []
        for group_name, payload in selections.items():
            experts = payload.get("experts") or []
            if not experts:
                continue
            groups[group_name] = {"experts": experts, "review_unit": payload.get("review_unit", "case")}
            created.append(group_name)
        db.set_setting("expert_groups", groups)
        return {"ok": True, "created": created}

    # -------------------------------------------------- export/import settings

    SETTINGS_EXPORT_VERSION = 1

    def export_settings(self, path: str) -> dict:
        try:
            payload = {
                "export_version": self.SETTINGS_EXPORT_VERSION,
                "criteria_config": self.config.to_dict(),
                "expert_groups": db.get_setting("expert_groups", {}) or {},
                "suspicious_rules": self.suspicious_rules,
                "analysis_rules": self.analysis_rules,
                "ai_settings": {  # عمداً بدون api_key (ریسک امنیتی انتقال کلید محرمانه بین سیستم‌ها)
                    "provider": self.ai_settings.provider, "model": self.ai_settings.model,
                    "base_url": self.ai_settings.base_url, "temperature": self.ai_settings.temperature,
                    "max_tokens": self.ai_settings.max_tokens, "batch_size": self.ai_settings.batch_size,
                    "enabled": self.ai_settings.enabled,
                },
            }
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "path": path}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return {"ok": False, "error": f"خطا در ذخیره فایل تنظیمات: {exc}"}

    def import_settings(self, path: str, mode: str = "merge") -> dict:
        """mode: 'merge' (گروه‌های جدید اضافه/به‌روزرسانی می‌شوند، گروه‌های
        موجودِ نام‌نبرده‌شده در فایل دست‌نخورده می‌مانند) یا 'replace'
        (گروه‌های فعلی کامل با فایل جایگزین می‌شوند)."""
        try:
            raw = Path(path).read_text(encoding="utf-8")
            payload = json.loads(raw)
        except FileNotFoundError:
            return {"ok": False, "error": "فایل انتخاب‌شده پیدا نشد."}
        except json.JSONDecodeError:
            return {"ok": False, "error": "فایل انتخاب‌شده یک JSON معتبر نیست (احتمالاً خراب یا فایل اشتباه است)."}

        version = payload.get("export_version")
        if version != self.SETTINGS_EXPORT_VERSION:
            return {"ok": False, "error": f"نسخه فایل تنظیمات ({version}) با این برنامه (نسخه {self.SETTINGS_EXPORT_VERSION}) سازگار نیست."}

        if "criteria_config" not in payload or "expert_groups" not in payload:
            return {"ok": False, "error": "ساختار فایل تنظیمات ناقص است (فیلدهای موردنیاز پیدا نشد)."}

        try:
            categories = [
                Category(id=c["id"], name_fa=c["name_fa"], criteria=[Criterion(**cr) for cr in c["criteria"]])
                for c in payload["criteria_config"]["categories"]
            ]
            self.config = CriteriaConfig(
                objective_ai_ratio=payload["criteria_config"]["objective_ai_ratio"],
                categories=categories,
                data_health_checks=payload["criteria_config"].get("data_health_checks", []),
            )
            save_criteria_config(self.config, USER_CONFIG_PATH)
        except (KeyError, TypeError) as exc:
            return {"ok": False, "error": f"ساختار معیارها در فایل نامعتبر است: {exc}"}

        incoming_groups = payload.get("expert_groups", {})
        if mode == "replace":
            db.set_setting("expert_groups", incoming_groups)
        else:
            current = db.get_setting("expert_groups", {}) or {}
            current.update(incoming_groups)
            db.set_setting("expert_groups", current)

        if "suspicious_rules" in payload:
            self.suspicious_rules = normalized_rule_settings(payload.get("suspicious_rules"))
            db.set_setting("suspicious_rules", self.suspicious_rules)
        if "analysis_rules" in payload:
            self.analysis_rules = normalize_analysis_rules(payload.get("analysis_rules"))
            db.set_setting("analysis_rules", self.analysis_rules)

        ai_payload = payload.get("ai_settings")
        if ai_payload:
            self.ai_settings.provider = ai_payload.get("provider", self.ai_settings.provider)
            self.ai_settings.model = ai_payload.get("model", self.ai_settings.model)
            self.ai_settings.base_url = ai_payload.get("base_url", self.ai_settings.base_url)
            self.ai_settings.temperature = ai_payload.get("temperature", self.ai_settings.temperature)
            self.ai_settings.max_tokens = ai_payload.get("max_tokens", self.ai_settings.max_tokens)
            self.ai_settings.batch_size = ai_payload.get("batch_size", self.ai_settings.batch_size)
            self.ai_settings.enabled = ai_payload.get("enabled", self.ai_settings.enabled)
            db.set_setting("ai_settings", ai_payload)

        return {
            "ok": True,
            "imported_groups": list(incoming_groups.keys()),
            "note": "کلید API (در صورت وجود) به‌دلایل امنیتی منتقل نشد؛ در صورت نیاز آن را در تنظیمات AI دوباره وارد کنید.",
        }

    # ------------------------------------------------------------ criteria --

    def get_criteria(self) -> dict:
        return self.config.to_dict()

    def set_criterion_threshold(self, criterion_id: str, threshold=None) -> dict:
        import math
        criterion = self.config.find_criterion(criterion_id)
        if not criterion:
            return {"ok": False, "error": "معیار یافت نشد."}
        try:
            number = None if threshold is None or threshold == "" else float(threshold)
        except (ValueError, TypeError):
            return {"ok": False, "error": "حدنصاب باید عدد باشد."}
        if number is not None and (not math.isfinite(number) or not 0 <= number <= 100):
            return {"ok": False, "error": "حدنصاب کیفی باید بین صفر و صد باشد."}
        criterion.pass_threshold = number
        save_criteria_config(self.config, USER_CONFIG_PATH)
        return {"ok": True}

    def update_criterion(self, criterion_id: str, weight: float, active: bool) -> dict:
        if criterion_id in {"notes_clarity", "notes_writing_quality", "task_description_quality", "scenario_recorded"}:
            return {"ok": False, "error": "این شاخص طول/کلیدواژه کنار گذاشته شده و معیار کیفیت محسوب نمی‌شود."}
        c = self.config.find_criterion(criterion_id)
        if not c:
            return {"ok": False, "error": "معیار پیدا نشد."}
        c.weight = float(weight)
        c.active = bool(active)
        save_criteria_config(self.config, USER_CONFIG_PATH)
        return {"ok": True}

    def update_evaluation_profile(self, profile_id: str, service_values: list[str],
                                  keywords: list[str], criteria_ids: list[str]) -> dict:
        profile = next((p for p in self.config.evaluation_profiles if p.id == profile_id), None)
        if not profile:
            return {"ok": False, "error": "پروفایل ارزیابی پیدا نشد."}
        profile.service_values = [str(v).strip() for v in service_values if str(v).strip()]
        profile.keywords = [str(v).strip() for v in keywords if str(v).strip()]
        profile.criteria_ids = [str(v) for v in criteria_ids]
        save_criteria_config(self.config, USER_CONFIG_PATH)
        return {"ok": True}

    def reset_criteria(self) -> dict:
        self.config = load_criteria_config()
        if USER_CONFIG_PATH.exists():
            USER_CONFIG_PATH.unlink()
        return {"ok": True}

    # ----------------------------------------------------------- AI settings

    def get_ai_settings(self) -> dict:
        s = self.ai_settings
        return {
            "provider": s.provider, "model": s.model, "base_url": s.base_url,
            "temperature": s.temperature, "max_tokens": s.max_tokens, "batch_size": s.batch_size,
            "enabled": s.enabled, "api_key_masked": db.mask_key(s.api_key), "has_key": bool(s.api_key),
        }

    def get_ai_presets(self) -> list[dict]:
        """Built-in starter configurations; keys are never included or stored."""
        return [
            {
                "id": "openrouter-free",
                "name": "OpenRouter Free Router (پیشنهادی)",
                "provider": "custom", "model": "openrouter/free",
                "base_url": "https://openrouter.ai/api/v1",
                "note": "نیازمند API Key رایگان OpenRouter؛ انتخاب خودکار مدل‌های رایگان",
            },
            {
                "id": "gemini-flash",
                "name": "Google Gemini 3.6 Flash (پیشنهادی)",
                "provider": "gemini", "model": "gemini-3.6-flash",
                "base_url": "", "note": "نیازمند API Key رایگان Google AI Studio",
            },
            {
                "id": "gemini-flash-lite",
                "name": "Google Gemini 3.6 Flash (گزینه جایگزین)",
                "provider": "gemini", "model": "gemini-3.6-flash",
                "base_url": "", "note": "نیازمند API Key رایگان Google AI Studio",
            },
            {
                "id": "openrouter-llama-free",
                "name": "Llama 3.3 8B via OpenRouter (Free)",
                "provider": "custom", "model": "meta-llama/llama-3.3-8b-instruct:free",
                "base_url": "https://openrouter.ai/api/v1",
                "note": "نیازمند API Key OpenRouter و وابسته به سهمیه مدل",
            },
            {
                "id": "ollama-local",
                "name": "Ollama Local — بدون هزینه سرویس",
                "provider": "custom", "model": "llama3.2",
                "base_url": "http://localhost:11434/v1",
                "note": "نیازمند نصب و اجرای Ollama روی همین رایانه",
            },
        ]

    def save_ai_settings(self, payload: dict) -> dict:
        s = self.ai_settings
        s.provider = payload.get("provider", s.provider)
        s.model = payload.get("model", s.model)
        s.base_url = payload.get("base_url", s.base_url)
        s.temperature = float(payload.get("temperature", s.temperature))
        s.max_tokens = int(payload.get("max_tokens", s.max_tokens))
        s.batch_size = int(payload.get("batch_size", s.batch_size))
        s.enabled = bool(payload.get("enabled", s.enabled))
        new_key = payload.get("api_key")
        if new_key:
            s.api_key = new_key
            db.save_api_key(new_key)
        db.set_setting("ai_settings", {
            "provider": s.provider, "model": s.model, "base_url": s.base_url,
            "temperature": s.temperature, "max_tokens": s.max_tokens,
            "batch_size": s.batch_size, "enabled": s.enabled,
        })
        return {"ok": True}

    def delete_ai_key(self) -> dict:
        db.delete_api_key()
        self.ai_settings.api_key = ""
        return {"ok": True}

    def test_ai_connection(self) -> dict:
        from ai.providers import AIProviderError, get_provider
        if not self.ai_settings.api_key:
            return {"ok": False, "message": "کلید API ثبت نشده است."}
        try:
            provider = get_provider(self.ai_settings)
            reply = provider.complete(
                "فقط یک شیء JSON به فرم {\"ok\": true} برگردان.", "تست اتصال", self.ai_settings
            )
            return {"ok": True, "message": f"اتصال موفق بود. پاسخ نمونه: {reply[:120]}"}
        except AIProviderError as exc:
            return {"ok": False, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"خطای غیرمنتظره: {exc}"}

    # ------------------------------------------------------------ analysis --

    def start_analysis(self, expert_group: str | None = None, force_ai: bool = False,
                        selected_case_keys: list[str] | None = None) -> dict:
        if not self.dataset:
            return {"ok": False, "error": "ابتدا داده CRM را دریافت یا Snapshot محلی را بازیابی کنید."}
        mode = "general"
        selected_keys = set(self.dataset.cases.keys()) if selected_case_keys is None else set(selected_case_keys)
        selected_keys &= set(self.dataset.cases.keys())
        if not selected_keys:
            return {"ok": False, "error": "حداقل یک مورد را برای تحلیل انتخاب کنید."}
        expert_filter = None
        unit = "case"
        if expert_group:
            groups = db.get_setting("expert_groups", {}) or {}
            group_data = groups.get(expert_group)
            if isinstance(group_data, list):
                group_data = {"experts": group_data, "review_unit": "case"}
            if not group_data or not group_data.get("experts"):
                return {"ok": False, "error": f"گروه «{expert_group}» یافت نشد یا خالی است."}
            expert_filter = set(group_data["experts"])
            unit = group_data.get("review_unit", "case")

        with self._lock:
            self._analysis_generation += 1
            generation = self._analysis_generation
            cancel_event = threading.Event()
            self._analysis_cancel_event = cancel_event
            dataset = self.dataset
            config = copy.deepcopy(self.config)
            ai_settings = copy.deepcopy(self.ai_settings)
            self.result = None
            self.status = {"running": True, "done": False, "cancelled": False, "stage": "شروع", "current": 0, "total": 0,
                           "error": None, "generation": generation, "mode": mode,
                           "selected_case_count": len(selected_keys)}
        thread = threading.Thread(
            target=self._run_worker,
            args=(dataset, config, ai_settings, expert_filter, unit, generation, force_ai, cancel_event, selected_keys),
            daemon=True,
        )
        thread.start()
        return {"ok": True, "generation": generation, "mode": mode}

    def cancel_analysis(self) -> dict:
        with self._lock:
            if not self.status.get("running"):
                return {"ok": False, "cancelled": False, "message": "تحلیلی در حال اجرا نیست."}
            if self._analysis_cancel_event:
                self._analysis_cancel_event.set()
            self.status.update({
                "running": False, "done": False, "cancelled": True,
                "stage": "تحلیل لغو شد", "error": None,
            })
        return {"ok": True, "cancelled": True}

    def _run_worker(self, dataset, config, ai_settings,
                    expert_filter=None, unit="case", generation=0,
                    force_ai=False, cancel_event: threading.Event | None = None,
                    selected_case_keys: set[str] | None = None):
        def progress_cb(label, current, total):
            with self._lock:
                if generation != self._analysis_generation:
                    return
                if cancel_event and cancel_event.is_set():
                    raise AnalysisCancelled()
                self.status.update({"stage": label, "current": current, "total": total})

        def cancel_check():
            if cancel_event and cancel_event.is_set():
                raise AnalysisCancelled()

        try:
            settings = ai_settings if ai_settings.enabled else AISettings(enabled=False)
            # دفاع نهایی در برابر نشت موارد انتخاب‌نشده: در حالت بررسی Case،
            # خود Dataset کاری Worker فقط شامل انتخاب‌های کاربر است.
            # این محدودسازی مستقل از فیلترهای UI و منطق هر Mode عمل می‌کند.
            analysis_dataset = dataset
            if selected_case_keys is not None:
                analysis_dataset = copy.copy(dataset)
                selected_bundles = {
                    key: case for key, case in dataset.cases.items()
                    if key in selected_case_keys
                }
                analysis_dataset.cases = dict(selected_bundles)
                selected_task_ids = {
                    id(link.task)
                    for case in selected_bundles.values()
                    for link in case.task_links
                }
                analysis_dataset.tasks = [
                    task for task in dataset.tasks
                    if id(task) in selected_task_ids
                    or (task.case_number and task.case_number in selected_case_keys)
                ]
                analysis_dataset.notes = [
                    note for note in dataset.notes
                    if note.case_key in selected_case_keys
                ]
            result = run_general_analysis(
                analysis_dataset, config, settings, progress_cb, expert_filter, unit,
                force_ai, cancel_check, selected_case_keys, self.suspicious_rules,
                {**self.analysis_rules, "management_thresholds": db.get_setting("management_thresholds", {}),
                 "management_severities": db.get_setting("management_severities", {})}
            )
            with self._lock:
                if generation != self._analysis_generation or (cancel_event and cancel_event.is_set()):
                    return
                analyzed_count = len(result["general"].cases)
                analysis_timestamp = datetime.now().isoformat()
                result["_analyzed_at"] = analysis_timestamp
                result["_case_analyzed_at"] = {
                    str(key): analysis_timestamp
                    for key in (selected_case_keys or set())
                }
                self.result = result
                snapshot = db.get_latest_crm_snapshot()
                db.save_local_analysis(
                    result,
                    dataset_id=_dataset_id(snapshot) if snapshot else None,
                    view_name=(snapshot or {}).get("view_name") if snapshot else None,
                )
                self.status.update({
                    "running": False, "done": True, "stage": "پایان یافت",
                    "analyzed_case_count": analyzed_count,
                    "eligible_case_count": analyzed_count,
                })
        except AnalysisCancelled:
            with self._lock:
                if generation == self._analysis_generation and self.status.get("running"):
                    self.status.update({
                        "running": False, "done": False, "cancelled": True,
                        "stage": "تحلیل لغو شد", "error": None,
                    })
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            with self._lock:
                if generation == self._analysis_generation:
                    self.status.update({"running": False, "done": False, "cancelled": False, "error": str(exc)})

    def get_status(self) -> dict:
        with self._lock:
            return dict(self.status)

    # ------------------------------------------------------------ results --

    def get_dashboard(self) -> dict:
        if not self.result or not self.dataset:
            return {"ok": False}
        r = self.result
        general = r["general"]
        return {
            "ok": True, "mode": "general", "unit": r.get("unit", "case"),
            "total_cases": len(general.cases), "total_cases_all": len(self.dataset.cases),
            "total_experts": len(r["experts_general"]),
            "total_notes": sum(len(c.notes) for c in general.cases.values()),
            "total_tasks": sum(len(c.tasks) for c in general.cases.values()),
            "data_quality": r["data_health_index"],
            "general_score": r["general_score"],
            "category_chart": [
                {"name": c["name_fa"], "value": c["value"]}
                for c in r["general_categories"]
            ],
            "suspicious_count": len(r["suspicious"]),
        }


    def get_ranking(self) -> dict:
        if not self.result:
            return {"ok": False}
        return {"ok": True, "rows": self.result["ranking"]}

    def get_expert_detail(self, expert: str) -> dict:
        if not self.result:
            return {"ok": False}
        r = self.result
        s = r["experts_general"].get(expert)
        if not s:
            return {"ok": True, "general": None, "cases": [], "feedback": None}
        from analysis.experts import build_employee_feedback, primary_expert
        cases = []
        for key, case in r["general"].cases.items():
            if primary_expert(case) == expert:
                b = r["general"].scores.get(key)
                cases.append({
                    "case_key": key, "case_number": case.case_number,
                    "case_title": case.case_title,
                    "final_score": b.final_score if b else None,
                })
        cases.sort(key=lambda c: (c["final_score"] is None, c["final_score"] or 0))
        return {
            "ok": True, "general": {
                "case_count": s.case_count, "note_count": s.note_count,
                "task_count": s.task_count, "avg_objective": s.avg_objective,
                "avg_ai": s.avg_ai, "avg_final": s.avg_final,
                "weak_criteria": s.weak_criteria.most_common(5),
                "strong_criteria": s.strong_criteria.most_common(5),
            },
            "cases": cases[:200],
            "feedback": build_employee_feedback(s),
        }

    def _build_full_expert_report(self, expert: str) -> dict:
        from analysis.experts import build_full_employee_report
        r = self.result
        stats = r["experts_general"].get(expert)
        return build_full_employee_report(
            expert, stats, r["experts_general"], "تحلیل کلی",
            unit=r.get("unit", "case"),
        )

    def get_expert_report(self, expert: str) -> dict:
        if not self.result:
            return {"ok": False, "error": "ابتدا تحلیل را اجرا کنید."}
        report = self._build_full_expert_report(expert)
        return {"ok": True, "report": report}

    def export_expert_report_excel(self, expert: str, path: str) -> dict:
        if not self.result:
            return {"ok": False, "error": "ابتدا تحلیل را اجرا کنید."}
        try:
            report = self._build_full_expert_report(expert)
            export_expert_report_excel_file(path, report)
            return {"ok": True, "path": path}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return {"ok": False, "error": f"خطا در ساخت گزارش: {exc}"}

    def _resolve_period(self, period: str = "general") -> tuple[dict, dict]:
        if not self.result or "general" not in self.result:
            return {}, {}
        return self.result["general"].cases, self.result["general"].scores

    def get_case_detail(self, case_key: str, period: str = "general") -> dict:
        if self.result:
            cases, scores = self._resolve_period(period)
        elif self.dataset:
            # Case details must remain available from the local snapshot even
            # before an analysis has been executed.
            cases, scores = self.dataset.cases, {}
        else:
            return {"ok": False}
        case = cases.get(case_key) or (self.dataset.cases.get(case_key) if self.dataset else None)
        if not case:
            return {"ok": False, "error": "مورد پیدا نشد."}
        breakdown = scores.get(case_key)
        timeline = build_timeline(case)
        return {
            "ok": True,
            "case_number": case.case_number, "case_title": case.case_title,
            "customer": case.customer, "owner": case.owner, "service": case.service,
            "status": case.status, "status_reason": case.status_reason,
            "scenario": case.scenario, "case_description": case.case_description,
            "timeline": timeline,
            "breakdown": _breakdown_to_dict(breakdown) if breakdown else None,
            "ai_analyzed": bool(breakdown and breakdown.ai_used) or is_case_ai_analyzed(
                case, self.config, self.ai_settings
            ),
            "ai_analysis": db.get_latest_ai_analysis(
                case.case_key,
                _case_signature(
                    case,
                    [c for _, c in self.config.active_criteria()
                     if c.evaluation_type in ("AI", "HYBRID")],
                    self.ai_settings,
                ),
            ),
            "ai_tag": (
                db.get_latest_ai_analysis(
                    case.case_key,
                    _case_signature(
                        case,
                        [c for _, c in self.config.active_criteria()
                         if c.evaluation_type in ("AI", "HYBRID")],
                        self.ai_settings,
                    ),
                )
            ),
            "improvement_suggestions": db.get_ai_suggestions(
                _case_signature(
                    case,
                    [c for _, c in self.config.active_criteria()
                     if c.evaluation_type in ("AI", "HYBRID")],
                    self.ai_settings,
                )
            ),
        }

    def start_case_ai_analysis(self, case_key: str, force: bool = False) -> dict:
        if not self.dataset:
            return {"ok": False, "error": "ابتدا فایل‌های داده را بارگذاری کنید."}
        case = self.dataset.cases.get(case_key)
        if not case:
            return {"ok": False, "error": "کیس پیدا نشد."}
        if not self.ai_settings.enabled or not self.ai_settings.api_key:
            return {"ok": False, "error": "تحلیل AI فعال نیست یا کلید API وارد نشده است."}
        ai_criteria = [c for _, c in self.config.active_criteria()
                       if c.evaluation_type in ("AI", "HYBRID")]
        signature = _case_signature(case, ai_criteria, self.ai_settings)
        if not force and db.has_successful_ai_analysis(case_key, signature):
            return {
                "ok": False,
                "already_analyzed": True,
                "error": "این مورد قبلاً با همین تنظیمات با موفقیت توسط AI تحلیل شده است. برای تحلیل مجدد تأیید کنید.",
            }
        with self._lock:
            if self._case_ai_status.get(case_key, {}).get("running"):
                return {"ok": True, "running": True, "case_key": case_key}
            self._case_ai_status[case_key] = {"running": True, "done": False, "error": None}
        threading.Thread(
            target=self._run_case_ai_worker,
            args=(case_key, copy.deepcopy(case), copy.deepcopy(self.config),
                  copy.deepcopy(self.ai_settings), force),
            daemon=True,
        ).start()
        return {"ok": True, "running": True, "case_key": case_key}

    def _run_case_ai_worker(self, case_key, case, config, settings, force):
        try:
            criteria = [c for _, c in config.active_criteria()
                        if c.evaluation_type in ("AI", "HYBRID")]
            if not criteria:
                raise RuntimeError("هیچ معیار AI فعالی برای این کیس وجود ندارد.")
            scores, error = analyze_case(case, criteria, settings, force=force)
            if error:
                message = str(error)
                if "criteria" in message.casefold() or "keyerror" in message.casefold():
                    message = "پاسخ سرویس AI ساختار معتبر نداشت و قابل استفاده نبود. اتصال، مدل و قالب پاسخ JSON را بررسی کنید."
                raise RuntimeError(message)
            if not scores:
                raise RuntimeError(
                    "سرویس AI پاسخ قابل استفاده‌ای برای معیارهای این کیس برنگرداند. "
                    "لطفاً اتصال، مدل و قالب پاسخ JSON را بررسی کنید."
                )
            evaluation_at = datetime.now().astimezone().isoformat()
            breakdown = score_case(case, config, scores, rule_settings={**self.analysis_rules, "evaluation_at": evaluation_at})
            with self._lock:
                if self.result:
                    for name in ("general",):
                        result = self.result.get(name)
                        if result and case_key in result.cases:
                            result.scores[case_key] = breakdown
                    # Previous managerial evaluation has a different frozen
                    # clock/config: never display it as the new AI result.
                    self.result.pop("quantitative", None)
                    self.result.pop("management_queue", None)
                    self.result.setdefault("_case_analyzed_at", {})[case_key] = evaluation_at
                    snapshot = db.get_latest_crm_snapshot()
                    db.save_local_analysis(self.result, dataset_id=_dataset_id(snapshot),
                                           view_name=(snapshot or {}).get("view_name"))
                self._case_ai_status[case_key] = {"running": False, "done": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._case_ai_status[case_key] = {"running": False, "done": False, "error": str(exc)}

    def get_case_ai_status(self, case_key: str) -> dict:
        with self._lock:
            return dict(self._case_ai_status.get(
                case_key, {"running": False, "done": False, "error": None}
            ))

    def get_cases_table(self, period: str, page: int, page_size: int,
                         expert_filter: str | None = None, status_reason_filter: list[str] | None = None,
                         case_number_filter: str | None = None,
                         service_filter: str | None = None,
                         ai_status_filter: str | None = None) -> dict:
        if self.result:
            cases, scores = self._resolve_period(period)
            unit = self.result.get("unit", "case")
        elif self.dataset:
            # The details grid is a data browser, not an analysis-only view.
            # Use the locally persisted CRM/file dataset when no result exists.
            cases, scores = self.dataset.cases, {}
            unit = "case"
        else:
            return {
                "ok": False,
                "error": "هنوز داده‌ای در بانک محلی برنامه وجود ندارد؛ ابتدا داده را از CRM یا فایل دریافت کنید.",
            }
        from analysis.experts import primary_expert
        rows = []
        snapshot = db.get_latest_crm_snapshot()
        fetched_at = (
            (snapshot or {}).get("metadata", {}).get("fetched_at")
            or (snapshot or {}).get("fetched_at")
        )
        analysis_record = db.get_local_analysis_record() or {}
        analysis_at = analysis_record.get("saved_at")
        case_analysis_times = self.result.get("_case_analyzed_at", {})
        experts_seen = set()
        status_reasons_seen = set()
        services_seen = set()
        query = (case_number_filter or "").strip().casefold()
        for key, case in cases.items():
            expert = primary_expert(case)
            experts_seen.add(expert)
            if case.status_reason:
                status_reasons_seen.add(case.status_reason)
            if case.service:
                services_seen.add(case.service)
            if expert_filter and expert != expert_filter:
                continue
            if status_reason_filter and (case.status_reason or "") not in status_reason_filter:
                continue
            if query and query not in (case.case_number or "").casefold():
                continue
            if service_filter and (case.service or "") != service_filter:
                continue
            b = scores.get(key)
            ai_analyzed = bool(b and b.ai_used) or is_case_ai_analyzed(
                case, self.config, self.ai_settings
            )
            if ai_status_filter == "analyzed" and not ai_analyzed:
                continue
            if ai_status_filter == "unanalyzed" and ai_analyzed:
                continue
            rows.append({
                "case_key": key, "case_number": case.case_number, "case_title": case.case_title,
                "expert": expert, "status_reason": case.status_reason,
                "service": case.service,
                "notes": len(case.notes), "tasks": len(case.tasks),
                "objective_score": b.objective_score if b else None,
                "ai_score": b.ai_score if b else None,
                "final_score": b.final_score if b else None,
                "ai_analyzed": ai_analyzed,
                "last_fetched_at": fetched_at,
                "last_analyzed_at": case_analysis_times.get(str(key), analysis_at),
            })
        rows.sort(key=lambda r: (r["final_score"] is None, r["final_score"] or 0))
        total = len(rows)
        start = page * page_size
        return {
            "ok": True, "rows": rows[start:start + page_size], "total": total,
            "experts": sorted(experts_seen), "status_reasons": sorted(status_reasons_seen),
            "services": sorted(services_seen),
            "unit": unit,
        }

    def get_suspicious(self, expert_filter: str | None = None,
                       reason_filter: list[str] | None = None,
                       service_filter: str | None = None) -> dict:
        if not self.result:
            return {"ok": False}
        from analysis.experts import primary_expert
        from analysis.suspicious import normalize_reason
        all_rows = self.result["suspicious"]
        snapshot = db.get_latest_crm_snapshot() or {}
        snapshot_meta = snapshot.get("metadata") or {}
        fetched_at = snapshot_meta.get("fetched_at") or snapshot.get("fetched_at")
        analysis_at = (db.get_local_analysis_record() or {}).get("saved_at")
        case_analysis_times = self.result.get("_case_analyzed_at", {})
        source_result = self.result.get("general")
        source_cases = source_result.cases if source_result else (
            self.dataset.cases if self.dataset else self.result["general"].cases
        )
        def source_case(case_key):
            return source_cases.get(case_key) or (
                self.dataset.cases.get(case_key) if self.dataset else None
            )
        rows = [
            {"case_key": s.case_key, "case_number": s.case_number, "case_title": s.case_title,
             "service": source_case(s.case_key).service if source_case(s.case_key) else None,
             "reasons": s.reasons,
             "last_fetched_at": fetched_at,
             "last_analyzed_at": case_analysis_times.get(str(s.case_key), analysis_at)}
            for s in all_rows
            if (not expert_filter or (
                source_case(s.case_key)
                and primary_expert(
                    source_case(s.case_key)
                ) == expert_filter
            ))
            and (not reason_filter or any(
                normalize_reason(reason) in reason_filter for reason in s.reasons
            ))
            and (not service_filter or (
                source_case(s.case_key) and source_case(s.case_key).service == service_filter
            ))
        ]
        experts = sorted({primary_expert(c) for c in source_cases.values()})
        reasons = sorted({
            normalize_reason(reason) for s in all_rows for reason in s.reasons
        })
        services = sorted({
            c.service for c in source_cases.values() if c.service
        })
        return {"ok": True, "rows": rows, "experts": experts, "reasons": reasons,
                "services": services,
                "unit": self.result.get("unit", "case")}

    def get_analysis_rules(self) -> dict:
        return {"rules": self.analysis_rules, "info": RULE_SETTING_INFO}

    def save_analysis_rules(self, rules: dict) -> dict:
        self.analysis_rules = normalize_analysis_rules(rules or {})
        db.set_setting("analysis_rules", self.analysis_rules)
        return {"ok": True, "rules": self.analysis_rules}

    def get_suspicious_rules(self) -> dict:
        return {"rules": [], "retired": True,
                "message": "هشدارهای مستقل کنار گذاشته شده‌اند؛ صف بررسی از نتیجه معیارها و حدنصاب ادمین ساخته می‌شود."}

    def save_suspicious_rules(self, rules: dict) -> dict:
        return {"ok": False, "error": "قواعد هشدار قدیمی بازنشسته شده‌اند؛ حدنصاب معیارها را تنظیم کنید."}

    def get_data_quality(self) -> dict:
        if not self.result:
            return {"ok": False}
        checks = [
            {"id": h.id, "name_fa": h.name_fa, "healthy_score": h.healthy_score,
             "issue_count": h.issue_count, "detail_fa": h.detail_fa}
            for h in self.result["data_health_checks"]
        ]
        return {"ok": True, "checks": checks, "index": self.result["data_health_index"]}

    def get_management_report(self) -> dict:
        if not self.result:
            return {"ok": False}
        r = self.result
        queue = r.get("management_queue", [])
        violations = [row for row in queue if row["criterion"]["status"] == "needs_correction"]
        missing = [row for row in queue if row["criterion"]["status"] == "insufficient_data"]
        return {
            "ok": True,
            "overall_status": f"محدوده موارد منتخب: {len(r['general'].cases)} مورد؛ {len(violations)} نقض حدنصاب و {len(missing)} معیار با کمبود داده. امتیاز ترکیبی یا رتبه فردی تولید نمی‌شود.",
            "top_strengths": [],
            "top_weaknesses": [
                {"name": f"{row['case_number'] or row['case_key']} — {row['criterion']['name']}", "score": row["criterion"]["value"]}
                for row in violations
            ],
            "data_issues": sorted({row["criterion"]["name"] for row in missing}),
            "recommendations": [f"{row['case_number'] or row['case_key']}: {row['action']}" for row in violations],
        }

    # -------------------------------------------------------------- export --

    def export_excel_report(self, path: str) -> dict:
        if not self.result:
            return {"ok": False, "error": "ابتدا تحلیل را اجرا کنید."}
        try:
            data = self._build_export_tables()
            export_excel(path, data)
            return {"ok": True, "path": path}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return {"ok": False, "error": f"خطا در ساخت فایل خروجی: {exc}"}

    def export_csv_table(self, table: str, path: str) -> dict:
        if not self.result:
            return {"ok": False, "error": "ابتدا تحلیل را اجرا کنید."}
        data = self._build_export_tables()
        section = data.get(table)
        if not section:
            return {"ok": False, "error": "جدول موردنظر یافت نشد."}
        export_csv(path, section["headers"], section["rows"])
        return {"ok": True, "path": path}

    def _build_export_tables(self) -> dict:
        r = self.result
        general = r["general"]
        from analysis.experts import primary_expert
        summary_rows = [
            ["تعداد موارد منتخب", len(general.cases)],
            ["تعداد یادداشت موارد منتخب", sum(len(case.notes) for case in general.cases.values())],
            ["تعداد فعالیت موارد منتخب", sum(len(case.tasks) for case in general.cases.values())],
            ["شاخص سلامت داده CRM", r["data_health_index"]],
            ["زمان ثابت ارزیابی", r.get("evaluation_at")],
            ["نسخه معیارها", r.get("criteria_version")],
        ]
        case_rows = []
        ai_rows = []
        for key, case in general.cases.items():
            b = general.scores.get(key)
            case_rows.append([
                "تحلیل کلی", case.case_number, case.case_title, primary_expert(case),
                len(case.notes), len(case.tasks),
                b.objective_score if b else None, b.ai_score if b else None,
            ])
            if b and b.ai_used:
                for cs in b.criterion_scores:
                    if cs.evaluation_type in ("AI", "HYBRID") and cs.score is not None:
                        ai_rows.append(["تحلیل کلی", case.case_number, cs.name_fa, cs.score, cs.evidence])
        expert_rows = [
            [row["expert"], row["cases"], "مالک فعلی؛ بدون انتساب کیفیت تاریخی"]
            for row in r["ranking"]
        ]
        category_rows = [[c["name_fa"], c["value"]] for c in r["general_categories"]]
        criteria_rows = [[c["name_fa"], c["value"]] for c in r["general_criteria"]]
        dq_rows = [[h.name_fa, h.healthy_score, h.issue_count, h.detail_fa]
                   for h in r["data_health_checks"]]
        suspicious_rows = [
            [s.case_number, s.case_title, " | ".join(s.reasons)]
            for s in r["suspicious"]
        ]
        return {
            "summary": {"headers": ["شاخص", "مقدار"], "rows": summary_rows},
            "cases": {"headers": ["حالت", "شماره مورد", "عنوان", "مالک فعلی", "یادداشت", "فعالیت", "معیارهای Rule", "معیارهای AI"], "rows": case_rows},
            "experts": {"headers": ["مالک فعلی", "موارد", "محدودیت انتساب"], "rows": expert_rows},
            "criteria": {"headers": ["معیار", "امتیاز"], "rows": criteria_rows},
            "categories": {"headers": ["دسته", "امتیاز"], "rows": category_rows},
            "data_quality": {"headers": ["بررسی", "سلامت", "تعداد مشکل", "توضیح"], "rows": dq_rows},
            "ai_analysis": {"headers": ["حالت", "شماره مورد", "معیار", "امتیاز", "شواهد"], "rows": ai_rows},
            "management": {"headers": ["مورد", "معیار", "مقدار", "حدنصاب", "نتیجه", "شدت", "شواهد", "اقدام"],
                           "rows": [[row["case_number"] or row["case_key"], row["criterion"]["name"],
                                     json.dumps(row["criterion"]["value"], ensure_ascii=False), row["criterion"]["threshold"],
                                     row["criterion"]["status"], row["criterion"]["severity"],
                                     json.dumps(row["criterion"]["evidence"], ensure_ascii=False, default=str), row["action"]]
                                    for row in r.get("management_queue", [])]},
            "suspicious": {"headers": ["شماره مورد", "عنوان", "دلایل"], "rows": suspicious_rows},
        }


def _summary_to_dict(s) -> dict:
    return {
        "file_name": s.file_name, "sheet_name": s.sheet_name, "total_rows": s.total_rows,
        "usable_rows": s.usable_rows, "rows_without_date": s.rows_without_date,
        "unique_cases": s.unique_cases, "incomplete_rows": s.incomplete_rows,
        "usable_columns": s.usable_columns, "total_columns": s.total_columns,
        "missing_required_labels": s.missing_required_labels, "warnings": s.warnings,
        "unmatched_headers": s.unmatched_headers,
    }


def _breakdown_to_dict(b) -> dict:
    return {
        "objective_score": b.objective_score, "ai_score": b.ai_score, "final_score": b.final_score,
        "ai_used": b.ai_used, "category_scores": b.category_scores,
        "coverage": b.coverage, "confidence": b.confidence,
        "na_criteria": b.na_criteria, "criteria_version": b.criteria_version,
        "evaluation_at": getattr(b, "evaluation_at", None),
        "outcome_status": b.outcome_status, "lifecycle_status": b.lifecycle_status,
        "criteria": [
            {"id": c.criterion_id, "name_fa": c.name_fa, "category": c.category_name_fa,
             "type": c.evaluation_type, "score": c.score, "evidence": c.evidence,
             "coverage": c.coverage, "confidence": c.confidence,
             "na_reason": c.na_reason, "source_events": c.source_events,
             "criteria_version": c.criteria_version, "status": getattr(c, "status", "insufficient_data")}
            for c in b.criterion_scores
        ],
    }
