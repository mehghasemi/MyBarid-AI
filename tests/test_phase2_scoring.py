from datetime import datetime

from analysis.outcomes import classify_case_outcome
from analysis.scoring import score_case
from config.criteria_config import load_criteria_config
from data.cleaner import build_cases
from data.validator import NoteRecord, TaskRecord


def _note(**overrides):
    data = dict(
        note_id="n1", description="بررسی انجام شد و مشکل رفع شد.",
        case_number="C-1", case_title="دسترسی", customer=None, owner="A",
        service=None, case_status="Resolved", case_status_reason=None,
        case_created_on=datetime(2026, 1, 1, 9), note_date=datetime(2026, 1, 1, 10),
        case_created_by="A",
        note_author="A", assign_to=None, incident_type=None, case_description=None,
        scenario=None,
    )
    data.update(overrides)
    return NoteRecord(**data)


def _case(**overrides):
    cases, _ = build_cases([_note(**overrides)], [])
    return cases["C-1"]


def test_scoring_reports_coverage_and_na_for_disabled_ai():
    breakdown = score_case(_case(), load_criteria_config())
    assert 0 < breakdown.coverage < 1
    assert breakdown.na_criteria > 0
    assert breakdown.confidence in {"low", "medium", "high"}
    assert any(item.score is None and item.na_reason for item in breakdown.criterion_scores)


def test_outcome_is_separate_from_agent_score():
    outcome = classify_case_outcome(_case())
    assert outcome.lifecycle_status == "Resolved"
    assert outcome.outcome_status == "Solved"
    assert outcome.coverage == 1.0


def test_missing_lifecycle_does_not_invent_outcome():
    outcome = classify_case_outcome(_case(case_status=None))
    assert outcome.lifecycle_status is None
    assert outcome.outcome_status is None
    assert outcome.na_reason
