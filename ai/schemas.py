from __future__ import annotations

import json
import re
from typing import Any


VALID_CONFIDENCE = {"low", "medium", "high"}


def extract_json(text: str) -> dict | None:
    """Extract the first complete JSON object from an AI response.

    Providers sometimes wrap valid JSON in a Markdown fence or a short
    explanation. A greedy ``\\{.*\\}`` regex breaks when the explanation also
    contains braces or when the response includes more than one JSON block.
    ``raw_decode`` understands quoted braces and nested objects correctly.
    """
    if not isinstance(text, str):
        return None
    text = text.lstrip("\ufeff").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return None


def _criterion_payload(payload: dict, criterion_id: str) -> dict[str, Any]:
    criteria = payload.get("criteria")
    if isinstance(criteria, dict) and isinstance(criteria.get(criterion_id), dict):
        return criteria[criterion_id]
    return {
        "score": (payload.get("scores") or {}).get(criterion_id),
        "evidence": (payload.get("evidence") or {}).get(criterion_id),
        "confidence": payload.get("confidence"),
        "source_events": (payload.get("source_events") or {}).get(criterion_id),
        "na_reason": (payload.get("na_reason") or {}).get(criterion_id),
    }


def validate_case_analysis(payload: dict, expected_criteria: list[str]) -> tuple[bool, list[str]]:
    """Validate explainable AI output; unsupported/incomplete scores are rejected."""
    problems: list[str] = []
    if not isinstance(payload, dict):
        return False, ["payload"]
    criteria = payload.get("criteria")
    scores = payload.get("scores")
    if not isinstance(criteria, dict) and not isinstance(scores, dict):
        return False, ["criteria_or_scores"]

    for criterion_id in expected_criteria:
        item = _criterion_payload(payload, criterion_id)
        score = item.get("score")
        evidence = item.get("evidence")
        confidence = item.get("confidence") or payload.get("confidence")
        source_events = item.get("source_events")
        na_reason = item.get("na_reason")

        if not isinstance(item, dict):
            problems.append(f"{criterion_id}.object")
            continue
        if score is None:
            if not na_reason:
                problems.append(f"{criterion_id}.na_reason")
            continue
        if not isinstance(score, (int, float)) or not 0 <= score <= 100:
            problems.append(f"{criterion_id}.score")
        if not isinstance(evidence, (str, dict)) or not str(evidence).strip():
            problems.append(f"{criterion_id}.evidence")
        if confidence not in VALID_CONFIDENCE:
            problems.append(f"{criterion_id}.confidence")
        if source_events is not None and not isinstance(source_events, list):
            problems.append(f"{criterion_id}.source_events")

    return not problems, problems
