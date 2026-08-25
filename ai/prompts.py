from __future__ import annotations

import json

from analysis.timeline import build_timeline
from config.criteria_config import Criterion
from data.cleaner import CaseBundle


SYSTEM_PROMPT_TEMPLATE = """You are a CRM service-quality evaluator.

Evaluate only the supplied Case events. Never infer missing fields, SLA, status
history, customer outcome, ownership history, or waiting periods.

AI is allowed only for semantic criteria such as diagnosis/action, outcome
contribution, and documentation sufficiency. Do not score text length, word
count, sentence count, or keyword count as quality.

Every numeric score must include concrete evidence from an event, an event
reference when available, and confidence. If evidence is missing, contradictory,
template-like, copied, or too vague, return score=null and a na_reason.

Return JSON only in this shape:
{{
  "criteria": {{
    "<criterion_id>": {{
      "score": 0-100 or null,
      "evidence": "fact-based explanation",
      "source_events": [{{"event_type": "note|task", "event_id": "...", "event_date": "..."}}],
      "confidence": "low|medium|high",
      "na_reason": "required only when score is null"
    }}
  }},
  "confidence": "low|medium|high",
  "improvement_suggestions": []
}}

Criteria:
{criteria_list}

After the criteria, optionally return improvement suggestions based only on
repeated or concrete evidence in this Case. Suggestions are proposals only;
never change a Rule or score. Use only these criterion IDs:
notes_result_recorded, task_presence_when_needed, final_status_clear,
solution_appropriateness, problem_understanding.
Allowed suggestion types:
add_pattern, activate_criterion, new_rule.
Return an empty array when there is no reliable suggestion. When suggestions
exist, replace the empty array with:
[
  {{
    "type": "add_pattern|activate_criterion|new_rule",
    "criterion_id": "one allowed ID",
    "title": "short title",
    "problem": "what is missing or inconsistent",
    "suggestion": "specific proposed change",
    "evidence": "case event evidence",
    "confidence": "low|medium|high"
  }}
]
"""


def build_system_prompt(criteria: list[Criterion]) -> str:
    lines = "\n".join(
        f"- {criterion.id}: {criterion.name_fa} — {criterion.description_fa}"
        for criterion in criteria
    )
    return SYSTEM_PROMPT_TEMPLATE.format(criteria_list=lines)


def build_case_prompt(case: CaseBundle) -> str:
    timeline = build_timeline(case)
    payload = {
        "case_number": case.case_number,
        "case_title": case.case_title,
        "customer": case.customer,
        "service": case.service,
        "status": case.status,
        "status_reason": case.status_reason,
        "events": timeline,
    }
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)
