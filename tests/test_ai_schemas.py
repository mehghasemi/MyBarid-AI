from ai.schemas import extract_json, validate_case_analysis


def test_ai_schema_accepts_explainable_score():
    payload = {
        "criteria": {
            "diagnosis": {
                "score": 85,
                "evidence": "اقدام ثبت‌شده با مشکل گزارش‌شده منطبق است.",
                "source_events": [{"event_type": "note", "event_id": "n1"}],
                "confidence": "high",
            }
        }
    }
    valid, problems = validate_case_analysis(payload, ["diagnosis"])
    assert valid
    assert not problems


def test_ai_schema_requires_na_reason_for_missing_score():
    payload = {"criteria": {"diagnosis": {"score": None}}}
    valid, problems = validate_case_analysis(payload, ["diagnosis"])
    assert not valid
    assert "diagnosis.na_reason" in problems


def test_ai_schema_accepts_explicit_na():
    payload = {
        "criteria": {
            "diagnosis": {
                "score": None,
                "evidence": "",
                "na_reason": "رویداد کافی برای تشخیص وجود ندارد.",
            }
        }
    }
    valid, problems = validate_case_analysis(payload, ["diagnosis"])
    assert valid
    assert not problems


def test_extract_json_rejects_non_object():
    assert extract_json("[1, 2]") is None
