import threading
from types import SimpleNamespace

from planning import PlanningApiMixin, merge_payload, source_key
from database import db

VIEW = "00000000-0000-0000-0000-000000000001"


class Api(PlanningApiMixin):
    def __init__(self):
        self._lock = threading.RLock()
        self.dataset = "evaluation-data"
        self.result = "evaluation-result"

    def get_crm_settings(self):
        return {"base_url": "https://crm.example.test", "organization": "Main", "api_version": "v9.1"}


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "data.db")
    db.init_db()
    return Api()


def test_snapshot_sources_are_isolated_and_selection_persists(monkeypatch, tmp_path):
    api = setup(monkeypatch, tmp_path)
    db.save_crm_snapshot("dynamics365", "evaluation", "2026-01-01", {}, {"notes": []})
    selection = {"view_id": VIEW, "view_kind": "savedqueries", "view_name": "planning"}
    assert api.save_planning_settings(selection)["ok"]
    assert Api().get_planning_settings()["view_id"] == VIEW
    settings = db.get_setting("planning_crm_settings")
    db.save_crm_snapshot(source_key(settings), "planning", "2026-01-02", {}, {"notes": [], "tasks": []})
    assert db.get_latest_crm_snapshot()["view_name"] == "evaluation"
    assert db.get_latest_crm_snapshot(source_key(settings))["view_name"] == "planning"
    assert "password" not in settings


def test_merge_keeps_old_data_and_deduplicates_actual_changes():
    previous = {"notes": [{"note_id": "1", "description": "old"}, {"note_id": "2", "description": "same"}], "tasks": []}
    incoming = {"notes": [{"note_id": "1", "description": "new"}, {"note_id": "2", "description": "same"},
                          {"note_id": "3", "description": "added"}], "tasks": []}
    merged, changed = merge_payload(previous, incoming)
    assert changed["notes"] == 2
    assert len(merged["notes"]) == 3
    assert merge_payload(merged, incoming)[1]["notes"] == 0


def test_incremental_worker_does_not_touch_evaluation_and_failed_fetch_does_not_advance_cursor(monkeypatch, tmp_path):
    api = setup(monkeypatch, tmp_path)
    api.save_planning_settings({"view_id": VIEW, "view_kind": "savedqueries", "view_name": "planning"})
    settings = api.get_planning_settings()
    source = source_key(settings)
    db.save_crm_snapshot(source, "planning", "2026-01-02T00:00:00", {"cursor": "2026-01-02T00:00:00"},
                         {"notes": [{"note_id": "1", "description": "previous"}], "tasks": [], "planning_crm": {}})
    calls = []
    def fetch(**kwargs):
        calls.append(kwargs)
        return None, {"fetched_at": "2026-01-03T00:00:00"}
    monkeypatch.setattr(api, "_planning_client", lambda *args: SimpleNamespace(fetch_view_dataset=fetch))
    monkeypatch.setattr("planning.dataset_to_payload", lambda *args: {"notes": [{"note_id": "2", "description": "added"}], "tasks": []})
    api._planning_status = {"started_at": 0, "running": True}
    api._planning_worker(settings, {})
    assert calls[0]["since"] is not None
    assert len(db.get_latest_crm_snapshot(source)["payload"]["notes"]) == 2
    assert api.dataset == "evaluation-data" and api.result == "evaluation-result"
    cursor = db.get_latest_crm_snapshot(source)["metadata"]["cursor"]
    def fail(**kwargs):
        raise RuntimeError("network error")
    monkeypatch.setattr(api, "_planning_client", lambda *args: SimpleNamespace(fetch_view_dataset=fail))
    api._planning_worker(settings, {})
    assert db.get_latest_crm_snapshot(source)["metadata"]["cursor"] == cursor
    assert not api._planning_status["running"] and api._planning_status["error"]


def test_view_listing_never_changes_default_and_switching_view_changes_source(monkeypatch, tmp_path):
    api = setup(monkeypatch, tmp_path)
    api.save_planning_settings({"view_id": VIEW, "view_kind": "savedqueries", "view_name": "selected"})
    original = source_key(api.get_planning_settings())
    monkeypatch.setattr(api, "_planning_client", lambda *args: SimpleNamespace(list_note_views=lambda: []))
    assert api.get_planning_views()["ok"]
    assert api.get_planning_settings()["view_name"] == "selected"
    api.save_planning_settings({"view_id": "00000000-0000-0000-0000-000000000002", "view_kind": "savedqueries", "view_name": "other"})
    assert source_key(api.get_planning_settings()) != original
