from datetime import datetime, timedelta
from types import SimpleNamespace
import inspect

from analysis.management import evaluate_case, status_intervals, management_queue
from analysis.timing import task_deadlines, followup_delay
from analysis.experts import aggregate_experts
from ai.schemas import validate_case_analysis
from bridge import Api
from data.cleaner import build_cases
from crm_client import dataset_to_payload, dataset_from_payload
from tests.test_pipeline import make_note, make_task
from pipeline import Dataset
from database import db
from config.criteria_config import load_criteria_config
from ai.providers import AISettings
from pipeline import run_general_analysis


def case():
    cases, _ = build_cases([make_note(case_status="Active")], [])
    return cases["CAS-1"]


def test_evaluation_preserves_settings_and_includes_qualitative_queue():
    from data.validator import ValidationSummary
    c = case()
    summary = ValidationSummary("CRM", "CRM", 1, 1, 0, 1, 0, 0, 0, {}, [], {}, [])
    dataset = Dataset(c.notes, [], {c.case_key: c}, [], summary, summary)
    result = run_general_analysis(dataset, load_criteria_config(), AISettings(enabled=False),
                                  rule_settings={"management_thresholds": {"reopens": 1}})
    assert result["effective_rule_settings"]["management_thresholds"] == {"reopens": 1}
    assert result["effective_criteria"]
    assert result["evaluation_at"] == result["general"].scores[c.case_key].evaluation_at
    assert any(row["criterion"].get("category") == "qualitative"
               for row in result["management_queue"])
    assert result["general"].scores[c.case_key].final_score is None
    api = Api.__new__(Api)
    api.result = result
    api.dataset = dataset
    tables = api._build_export_tables()
    assert "Final" not in tables["cases"]["headers"]
    assert "management" in tables and "ai_analysis" in tables
    for table in tables.values():
        assert all(len(row) == len(table["headers"]) for row in table["rows"])
    assert "امتیاز ترکیبی" in api.get_management_report()["overall_status"]


def test_absent_tasks_and_events_are_not_automatic_failures():
    from analysis.rules import task_presence_when_needed, timeline_reconstructable
    c = case()
    c.case_description = "L2"
    assert task_presence_when_needed(c).score is None
    c.notes = []
    assert timeline_reconstructable(c).score is None


def test_case_histories_survive_snapshot_roundtrip():
    from data.validator import ValidationSummary
    c = case()
    c.history_complete = True
    c.status_history = [{"status": "Active", "kind": "open", "entered_at": c.created_on}]
    c.responsibility_history_complete = True
    c.responsibility_history = [{"owner_id": "one", "entered_at": c.created_on},
                                {"owner_id": "two", "entered_at": c.created_on + timedelta(hours=1)}]
    summary = ValidationSummary("CRM", "CRM", 1, 1, 0, 1, 0, 0, 0, {}, [], {}, [])
    dataset = Dataset(c.notes, [], {c.case_key: c}, [], summary, summary)
    restored = dataset_from_payload(dataset_to_payload(dataset)).cases[c.case_key]
    rows = {row["id"]: row for row in evaluate_case(restored, c.created_on + timedelta(hours=2))["criteria"]}
    assert rows["owner_changes"]["value"] == 1
    assert rows["status_dwell"]["value"] == {"Active": 2}


def test_catalog_contains_all_required_identity_fields():
    from config.criterion_catalog import criterion_catalog
    required = {"id", "category", "definition", "management_use", "data_source", "method", "unit",
                "desired_direction", "threshold", "weight", "applicability", "missing_data", "severity", "required_evidence"}
    assert all(required <= row.keys() for row in criterion_catalog(load_criteria_config()))


def test_severity_settings_do_not_turn_missing_data_into_failure(monkeypatch):
    api = Api.__new__(Api)
    api.config = load_criteria_config()
    stored = {}
    monkeypatch.setattr(db, "set_setting", lambda key, value: stored.update({key: value}))
    assert api.save_management_severities({"reopens": "critical"})["ok"]
    assert stored["management_severities"] == {"reopens": "critical"}
    assert not api.save_management_severities({"unknown": "critical"})["ok"]
    assert not api.save_management_severities({"reopens": "guess"})["ok"]
    result = evaluate_case(case(), datetime(2026, 1, 2))
    assert next(row for row in result["criteria"] if row["id"] == "reopens")["status"] == "insufficient_data"


def test_ai_analyzed_tag_requires_valid_cached_references(monkeypatch):
    from ai.analyzer import is_case_ai_analyzed
    c = case()
    config = load_criteria_config()
    payload = {"criteria": {item.id: {"score": 80, "evidence": "شاهد", "confidence": "medium",
        "source_events": [{"event_type": "note", "event_id": c.notes[0].note_id}]}
        for _, item in config.active_criteria() if item.evaluation_type in {"AI", "HYBRID"}}}
    monkeypatch.setattr(db, "get_ai_cache", lambda key: payload)
    assert is_case_ai_analyzed(c, config, AISettings(enabled=True, api_key="test-only"))
    for item in payload["criteria"].values():
        item["source_events"][0]["event_id"] = "nonexistent"
    assert not is_case_ai_analyzed(c, config, AISettings(enabled=True, api_key="test-only"))


def test_audit_reader_pages_and_never_claims_complete_status_history(monkeypatch):
    import crm_client
    calls = []
    def get(url, *credentials):
        calls.append(url)
        return {"AuditDetailCollection": {"AuditDetails": [{"NewValue": {"statuscode": 1}}],
                                          "MoreRecords": len(calls) == 1, "PagingCookie": "next"}}
    monkeypatch.setattr(crm_client, "_powershell_get_json", get)
    result = crm_client.DynamicsCRMClient().read_case_audit("00000000-0000-0000-0000-000000000001")
    assert result["pages"] == 2
    assert not result["history_complete"]
    assert len(result["details"]) == 2


def test_audit_reader_rejects_broken_paging(monkeypatch):
    import pytest
    import crm_client
    monkeypatch.setattr(crm_client, "_powershell_get_json", lambda *args: {"AuditDetailCollection": {
        "AuditDetails": [], "MoreRecords": True, "PagingCookie": "repeated"}})
    with pytest.raises(crm_client.CRMClientError):
        crm_client.DynamicsCRMClient().read_case_audit("00000000-0000-0000-0000-000000000001")


def test_report_exports_remain_available(tmp_path):
    from reports.excel_export import export_excel
    from reports.csv_export import export_csv
    from openpyxl import load_workbook
    section = {"headers": ["مورد"], "rows": [["CAS-1"]]}
    export_excel(str(tmp_path / "report.xlsx"), {"cases": section})
    workbook = load_workbook(tmp_path / "report.xlsx")
    assert workbook["Case Analysis"]["A2"].value == "CAS-1"
    assert workbook["Case Analysis"].sheet_view.rightToLeft
    export_csv(str(tmp_path / "report.csv"), section["headers"], section["rows"])
    assert "CAS-1" in (tmp_path / "report.csv").read_text(encoding="utf-8-sig")


def test_repeated_state_durations_are_sum_and_current_contiguous():
    c = case()
    start = c.created_on
    c.history_complete = True
    c.status_history = [
        {"status": "بررسی", "kind": "open", "entered_at": start},
        {"status": "منتظر مشتری", "kind": "waiting_customer", "entered_at": start + timedelta(hours=3)},
        {"status": "بررسی", "kind": "open", "entered_at": start + timedelta(hours=8)},
    ]
    values = {row["id"]: row for row in evaluate_case(c, (start+timedelta(hours=10)).isoformat())["criteria"]}
    assert values["status_dwell"]["value"] == {"بررسی": 5, "منتظر مشتری": 5}
    assert values["current_status_duration"]["value"] == 2
    assert values["status_entries"]["value"]["بررسی"] == 2


def test_incomplete_history_never_uses_case_modified_time():
    c = case()
    c.modified_on = datetime(2026, 1, 1)
    rows = evaluate_case(c, datetime(2026, 1, 2).isoformat())["criteria"]
    assert next(row for row in rows if row["id"] == "status_dwell")["status"] == "insufficient_data"


def test_future_open_task_is_not_failure_and_start_is_not_finish():
    now = datetime(2026, 1, 2)
    c = case()
    c.task_links = [SimpleNamespace(task=make_task(status_reason="In Progress", due_date=now+timedelta(days=1), actual_start=now))]
    assert task_deadlines(c, now)[0]["state"] == "not_due"
    c.tasks[0].status_reason = "Completed"
    assert task_deadlines(c, now)[0]["state"] == "insufficient_data"


def test_completed_task_uses_actual_end_and_open_overdue_is_separate():
    c = case()
    due = datetime(2026, 1, 2)
    c.task_links = [SimpleNamespace(task=make_task(due_date=due, actual_end=due+timedelta(hours=2)))]
    assert task_deadlines(c, due+timedelta(days=1))[0]["delay_hours"] == 2
    c.tasks[0].status_reason = "In Progress"
    assert task_deadlines(c, due+timedelta(days=1))[0]["state"] == "open_overdue"


def test_future_followup_is_not_zero_and_unrelated_note_does_not_prove_completion():
    c = case()
    now = datetime(2026, 1, 2)
    c.task_links = [SimpleNamespace(task=make_task(follow_up_needed="Yes", next_follow_up=now+timedelta(days=1)))]
    assert followup_delay(c, {"evaluation_at": now.isoformat()}).score is None


def test_invalid_history_order_and_unknown_initial_interval_rejected():
    c = case()
    c.history_complete = True
    c.status_history = [{"status": "open", "kind": "open", "entered_at": c.created_on+timedelta(hours=1)}]
    assert status_intervals(c, c.created_on+timedelta(hours=2))[0] is None


def test_reopen_count_and_closed_interval_not_waiting():
    c = case()
    c.history_complete = True
    start = c.created_on
    c.status_history = [{"status": kind, "kind": kind, "entered_at": start+timedelta(hours=i)}
                        for i, kind in enumerate(["open", "resolved", "open"])]
    rows = {r["id"]: r for r in evaluate_case(c, (start+timedelta(hours=3)).isoformat())["criteria"]}
    assert rows["reopens"]["value"] == 1
    assert rows["waiting_customer"]["value"] == 0


def test_threshold_failure_remains_visible_independent_of_average():
    c = case()
    due = datetime(2026, 1, 2)
    c.task_links = [SimpleNamespace(task=make_task(due_date=due, actual_end=due+timedelta(hours=2)))]
    evaluation = evaluate_case(c, (due+timedelta(days=1)).isoformat(), {"task_deadlines": 1})
    assert any(row["criterion"]["id"] == "task_deadlines" and row["criterion"]["status"] == "needs_correction"
               for row in management_queue([evaluation]))


def test_removed_apis_are_not_exposed():
    assert not hasattr(Api, "upload") and not hasattr(Api, "get_comparison")
    assert not hasattr(Api, "auto_upload_default_files")
    assert "p1_start" not in inspect.signature(Api.start_analysis).parameters


def test_ai_references_must_exist_in_case():
    c = case()
    payload = {"criteria": {"x": {"score": 80, "evidence": "شاهد", "confidence": "medium",
                                 "source_events": [{"event_type": "note", "event_id": "invented"}]}}}
    assert not validate_case_analysis(payload, ["x"], c)[0]
    payload["criteria"]["x"]["source_events"][0]["event_id"] = c.notes[0].note_id
    assert validate_case_analysis(payload, ["x"], c)[0]


def test_action_migration_preserves_existing_setting(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.set_setting("preserved", "yes")
    db.save_management_action("CAS-1", "task_deadlines", "پیگیری", "مدیر", "2026-10-11T10:00", "2026-10-10T10:00")
    assert db.get_setting("preserved") == "yes"
    assert db.get_management_actions()[0]["case_key"] == "CAS-1"
