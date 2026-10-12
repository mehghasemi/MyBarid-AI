from crm_history import reconstruct_history


def record():
    return {"createdon": "2026-10-12T00:00:00Z", "statecode": 0, "statuscode": 2, "_ownerid_value": "B"}


def details():
    return [
        {"AuditRecord": {"auditid": "create", "operation": 1, "createdon": "2026-10-12T00:00:00Z"}},
        {"AuditRecord": {"auditid": "change", "operation": 2, "createdon": "2026-10-12T02:00:00Z"},
         "OldValue": {"statuscode": 1, "_ownerid_value": "A"},
         "NewValue": {"statuscode": 2, "_ownerid_value": "B"}},
    ]


def test_real_history_reconstructs_status_and_owner_with_mapping():
    result = reconstruct_history(record(), details(), {"2": {"name": "منتظر مشتری", "kind": "waiting_customer"}})
    assert result["history_complete"]
    assert result["status_history"][0]["status_code"] == 1
    assert result["status_history"][1]["kind"] == "waiting_customer"
    assert [row["owner_id"] for row in result["responsibility_history"]] == ["A", "B"]


def test_missing_creation_or_discontinuous_audit_is_not_complete():
    assert not reconstruct_history(record(), details()[1:])["history_complete"]
    broken = details()
    broken[1]["NewValue"]["statuscode"] = 999
    assert not reconstruct_history(record(), broken)["history_complete"]


def test_missing_previous_value_is_not_invented():
    broken = details()
    broken[1]["OldValue"].pop("statuscode")
    assert not reconstruct_history(record(), broken)["history_complete"]
