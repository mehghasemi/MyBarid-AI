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
  "confidence": "low|medium|high"
}}

Criteria:
{criteria_list}
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
