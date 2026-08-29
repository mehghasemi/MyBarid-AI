from datetime import datetime
from unittest.mock import patch

from crm_client import (
    DynamicsCRMClient,
    _add_modified_since_filter,
    dataset_from_payload,
)
from database import db
from bridge import _dataset_id


def test_modified_since_filter_preserves_view_filters():
    fetchxml = (
        '<fetch><entity name="annotation">'
        '<filter type="and"><condition attribute="createdon" '
        'operator="last-x-days" value="2" /></filter>'
        '</entity></fetch>'
    )
    updated = _add_modified_since_filter(fetchxml, datetime(2026, 8, 29, 10, 30, 0))
    assert 'attribute="createdon"' in updated
    assert 'attribute="modifiedon"' in updated
    assert 'operator="gt"' in updated
    assert 'value="2026-08-29T10:30:00Z"' in updated


def test_crm_snapshot_round_trip_keeps_note_count():
    row = {
        "note_id": "n-1",
        "description": "نتیجه ثبت شد",
        "case_number": "CAS-1",
        "case_title": "عنوان",
        "customer": None,
        "owner": "کارشناس",
        "service": "سرویس",
        "case_status": "Resolved",
        "case_status_reason": "Completed",
        "case_created_on": "2026-08-29T10:00:00",
        "case_created_by": "کاربر",
        "note_date": "2026-08-29T10:30:00",
        "note_author": "کارشناس",
        "assign_to": None,
        "incident_type": None,
        "case_description": "شرح",
        "scenario": "سناریو",
    }
    dataset = dataset_from_payload({"notes": [row], "tasks": []})
    assert len(dataset.notes) == 1
    assert len(dataset.cases) == 1


def test_crm_view_fetch_follows_next_link_pages():
    def row(note_id, case_number):
        return {
            "annotationid": note_id,
            "notetext": "نتیجه ثبت شد",
            "ac.ticketnumber": case_number,
            "ac.title": f"عنوان {case_number}",
            "modifiedon": "2026-08-29T10:00:00Z",
        }

    responses = [
        {
            "value": [row("n-1", "CAS-1"), row("n-2", "CAS-2")],
            "@odata.nextLink": "https://crm.example/annotations?page=2",
        },
        {"value": [row("n-3", "CAS-3")]},
    ]
    client = DynamicsCRMClient(view_name="TESTNOTE")
    with patch("crm_client._powershell_get_json", side_effect=responses):
        with patch.object(client, "_get_user_view", return_value={"fetchxml": "<fetch><entity name='annotation'/></fetch>"}):
            dataset, metadata = client.fetch_view_dataset()

    assert len(dataset.notes) == 3
    assert metadata["row_count"] == 3


def test_crm_view_expands_all_case_notes_and_tasks():
    case_id = "11111111-1111-1111-1111-111111111111"
    responses = [
        {"value": [{
            "annotationid": "n-view",
            "notetext": "یادداشت View",
            "ac.ticketnumber": "CAS-1",
            "ac.title": "عنوان Case",
            "_objectid_value": case_id,
            "modifiedon": "2026-08-29T10:00:00Z",
        }]},
        {"value": [{
            "annotationid": "n-old",
            "notetext": "یادداشت قدیمی",
            "createdon": "2024-01-01T10:00:00Z",
            "_objectid_value": case_id,
        }]},
        {"value": [{
            "activityid": "t-old",
            "subject": "اقدام قدیمی",
            "description": "Task مرتبط با Case",
            "createdon": "2023-01-01T10:00:00Z",
            "_regardingobjectid_value": case_id,
        }]},
    ]
    client = DynamicsCRMClient(view_name="TESTNOTE")
    with patch("crm_client._powershell_get_json", side_effect=responses):
        with patch.object(
            client, "_get_user_view",
            return_value={"fetchxml": "<fetch><entity name='annotation'/></fetch>"},
        ):
            dataset, metadata = client.fetch_view_dataset()

    assert len(dataset.notes) == 2
    assert len(dataset.tasks) == 1
    assert len(dataset.cases["CAS-1"].notes) == 2
    assert len(dataset.cases["CAS-1"].tasks) == 1
    assert metadata["row_count"] == 2


def test_local_analysis_record_round_trip_keeps_metadata(tmp_path):
    original_path = db.DB_PATH
    db.DB_PATH = tmp_path / "app.db"
    try:
        db.init_db()
        value = {"mode": "general", "cases": []}
        db.save_local_analysis(value, dataset_id="snapshot-1", view_name="TESTNOTE")
        record = db.get_local_analysis_record()
        assert record["result"] == value
        assert record["dataset_id"] == "snapshot-1"
        assert record["view_name"] == "TESTNOTE"
        assert record["saved_at"]
    finally:
        db.DB_PATH = original_path


def test_dataset_id_is_not_affected_by_view_row_order():
    first = {"payload": {"notes": [{"note_id": "2"}, {"note_id": "1"}], "tasks": []}}
    second = {"payload": {"notes": [{"note_id": "1"}, {"note_id": "2"}], "tasks": []}}
    assert _dataset_id(first) == _dataset_id(second)
