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


def test_malformed_ai_payload_does_not_raise():
    from ai.analyzer import _payload_to_scores

    assert _payload_to_scores({"criteria": None}, ["diagnosis"]) == {}
    assert _payload_to_scores({}, ["diagnosis"]) == {}


def test_valid_na_ai_payload_is_preserved_for_case_breakdown():
    from ai.analyzer import _payload_to_scores

    result = _payload_to_scores(
        {"criteria": {"diagnosis": {"score": None, "na_reason": "شواهد کافی وجود ندارد."}}},
        ["diagnosis"],
    )
    assert result == {"diagnosis": (None, "شواهد کافی وجود ندارد.")}


def test_improvement_suggestions_are_limited_to_safe_proposals():
    from ai.analyzer import _extract_improvement_suggestions

    result = _extract_improvement_suggestions({
        "improvement_suggestions": [
            {
                "type": "add_pattern",
                "criterion_id": "notes_result_recorded",
                "title": "الگوی نتیجه",
                "problem": "واژه ثبت‌شده شناسایی نشده است.",
                "suggestion": "افزودن الگوی «نتیجه اقدام ثبت شد».",
                "evidence": "در Note کیس عبارت آمده است.",
                "confidence": "high",
            },
            {
                "type": "new_rule",
                "criterion_id": "unknown_criterion",
                "title": "نباید پذیرفته شود",
                "suggestion": "x",
                "evidence": "y",
            },
        ]
    })
    assert len(result) == 1
    assert result[0]["status"] == "proposed"
