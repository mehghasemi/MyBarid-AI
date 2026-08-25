from datetime import datetime, timedelta

from analysis.experts import primary_expert
from analysis.rules import notes_completeness, notes_result_recorded
from analysis.scoring import score_case
from config.criteria_config import load_criteria_config
from data.cleaner import build_cases
from data.mapper import NOTES_FIELDS, TASKS_FIELDS, detect_mapping
from data.validator import NoteRecord, TaskRecord


def make_note(**kwargs) -> NoteRecord:
    base = dict(
        note_id="n1", description="", case_number="CAS-1", case_title="عنوان تست",
        customer="مشتری", owner="کارشناس ۱", service="Service", case_status="Resolved",
        case_status_reason="Problem Solved", case_created_on=datetime(2026, 1, 1, 9, 0),
        case_created_by="کارشناس ۱", note_date=datetime(2026, 1, 1, 10, 0), note_author="کارشناس ۱",
        assign_to=None, incident_type=None, case_description=None, scenario=None,
    )
    base.update(kwargs)
    return NoteRecord(**base)


def make_task(**kwargs) -> TaskRecord:
    base = dict(
        task_id="t1", subject="تماس", description="", case_number="CAS-1", regarding="عنوان تست",
        created_by="کارشناس ۱", created_on=datetime(2026, 1, 1, 11, 0), actual_start=None,
        due_date=None, status_reason="Completed", follow_up_needed="No", next_follow_up=None,
        work_type=None, assign_to=None,
    )
    base.update(kwargs)
    return TaskRecord(**base)


# ---------------------------------------------------------------- Mapper --

def test_mapper_handles_real_dynamics_headers():
    headers = [
        "(Do Not Modify) Note", "(Do Not Modify) Row Checksum", "(Do Not Modify) Modified On",
        "Title", "Description", "Case Number (Regarding) (Case)", "Case Title (Regarding) (Case)",
        "Customer (Regarding) (Case)", "Status (Regarding) (Case)", "Modified By", "Modified On",
    ]
    result = detect_mapping(headers, NOTES_FIELDS)
    assert result.mapping["description"] == "Description"
    assert result.mapping["case_number"] == "Case Number (Regarding) (Case)"
    assert result.mapping["note_date"] == "(Do Not Modify) Modified On"
    assert not result.missing_required


def test_mapper_reports_missing_required():
    headers = ["Subject", "Regarding"]  # بدون Created On و Description
    result = detect_mapping(headers, TASKS_FIELDS)
    missing_ids = {s.name for s in result.missing_required}
    assert "created_on" in missing_ids


# ------------------------------------------------------------ Case link --

def test_build_cases_links_by_case_number():
    notes = [make_note()]
    tasks = [make_task(case_number="CAS-1")]
    cases, unmatched = build_cases(notes, tasks)
    assert "CAS-1" in cases
    assert len(cases["CAS-1"].task_links) == 1
    assert cases["CAS-1"].task_links[0].confidence == "high"
    assert not unmatched


def test_build_cases_falls_back_to_title_match():
    notes = [make_note()]
    tasks = [make_task(case_number=None, regarding="عنوان تست")]
    cases, unmatched = build_cases(notes, tasks)
    assert len(cases["CAS-1"].task_links) == 1
    assert cases["CAS-1"].task_links[0].confidence == "medium"
    assert not unmatched


def test_build_cases_reports_unmatched_task():
    notes = [make_note()]
    tasks = [make_task(case_number=None, regarding="عنوان کاملاً متفاوت")]
    cases, unmatched = build_cases(notes, tasks)
    assert len(unmatched) == 1
    assert not cases["CAS-1"].task_links


# ------------------------------------------------------------- Rules ----

def test_notes_completeness_full_text():
    notes = [make_note(description="مشتری اعلام کرد سیستم قطع است. بررسی و اقدام شد. مشکل برطرف شد.")]
    cases, _ = build_cases(notes, [])
    result = notes_completeness(cases["CAS-1"])
    assert result.score == 100


def test_notes_completeness_empty():
    notes = [make_note(description="")]
    cases, _ = build_cases(notes, [])
    result = notes_completeness(cases["CAS-1"])
    assert result.score == 0


def test_notes_result_recorded_resolved_without_evidence():
    notes = [make_note(description="بررسی شد.", case_status="Resolved")]
    cases, _ = build_cases(notes, [])
    result = notes_result_recorded(cases["CAS-1"])
    assert result.score == 20  # اقدام دیده می‌شود، اما نتیجه مستند نیست


def test_closed_case_with_action_but_without_result_is_flagged():
    notes = [make_note(description="اقدام برای startup انجام شد.", case_status="Closed")]
    cases, _ = build_cases(notes, [])
    result = notes_result_recorded(cases["CAS-1"])
    assert result.score == 20
    assert "result" in result.evidence


# ------------------------------------------------------------ Experts ---

def test_primary_expert_ignores_portal():
    notes = [
        make_note(note_author="portal portal", description="سلام مشکل دارم" * 5),
        make_note(note_author="کارشناس ۲", description="بررسی و رفع شد"),
    ]
    cases, _ = build_cases(notes, [])
    assert primary_expert(cases["CAS-1"]) == "کارشناس ۲"


# ------------------------------------------------------------ Scoring ---

def test_score_case_without_ai_uses_objective_only():
    notes = [make_note(description="مشکل قطعی سرویس بود. بررسی و اقدام شد. مشکل رفع شد و تست شد.")]
    tasks = [make_task(description="با کاربر تماس گرفته شد و سرویس ری‌استارت شد. نتیجه: مشکل برطرف شد.")]
    cases, _ = build_cases(notes, tasks)
    config = load_criteria_config()
    breakdown = score_case(cases["CAS-1"], config)
    assert breakdown.ai_used is False
    assert breakdown.ai_score is None
    assert breakdown.objective_score is not None
    assert breakdown.final_score == breakdown.objective_score


def test_score_case_combines_ai_when_provided():
    notes = [make_note(description="مشکل قطعی سرویس بود. بررسی و اقدام شد. مشکل رفع شد.")]
    cases, _ = build_cases(notes, [])
    config = load_criteria_config()
    ai_scores = {c.id: (90.0, "شواهد فرضی") for cat, c in config.active_criteria() if c.evaluation_type == "AI"}
    breakdown = score_case(cases["CAS-1"], config, ai_scores)
    assert breakdown.ai_used is True
    assert breakdown.ai_score == 90.0
    assert breakdown.final_score is not None
    assert breakdown.final_score != breakdown.objective_score


def test_active_criteria_have_audit_guides():
    config = load_criteria_config()
    missing = [
        criterion.id
        for _, criterion in config.active_criteria()
        if not criterion.goal_fa or not criterion.calculation_fa or not criterion.interpretation_fa
    ]
    assert missing == []
