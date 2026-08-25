from __future__ import annotations

import hashlib
import time
from typing import Callable

from ai.prompts import build_case_prompt, build_system_prompt
from ai.providers import AIProviderError, AISettings, get_provider
from ai.schemas import extract_json, validate_case_analysis
from config.criteria_config import CriteriaConfig
from data.cleaner import CaseBundle
from database import db

MAX_RETRIES = 2


def _case_signature(case: CaseBundle, criteria_ids: list[str], model: str) -> str:
    parts = [case.case_key, model, ",".join(sorted(criteria_ids))]
    for n in case.notes:
        parts.append(f"N|{n.note_date}|{n.description}")
    for t in case.tasks:
        parts.append(f"T|{t.created_on}|{t.description}")
    raw = "\n".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def analyze_case(
    case: CaseBundle, ai_criteria, settings: AISettings, use_cache: bool = True,
) -> tuple[dict[str, tuple[float, str]], str | None]:
    """یک Case را تحلیل می‌کند. خروجی: (scores_by_criterion, error_message).
    اگر AI شکست بخورد، دیکشنری خالی برمی‌گردد و پیام خطا پر می‌شود؛ هرگز امتیاز جعلی تولید نمی‌شود."""
    criteria_ids = [c.id for c in ai_criteria]
    if not criteria_ids:
        return {}, None

    sig = _case_signature(case, criteria_ids, settings.model)
    if use_cache:
        cached = db.get_ai_cache(sig)
        if cached:
            return _payload_to_scores(cached, criteria_ids), None

    provider = get_provider(settings)
    system = build_system_prompt(ai_criteria)
    user = build_case_prompt(case)

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            raw = provider.complete(system, user, settings)
        except AIProviderError as exc:
            last_error = str(exc)
            time.sleep(1.5 * (attempt + 1))
            continue
        payload = extract_json(raw)
        if payload is None:
            last_error = "خروجی AI یک JSON معتبر نبود."
            continue
        valid, problems = validate_case_analysis(payload, criteria_ids)
        if not valid:
            last_error = f"خروجی AI ناقص بود (فیلدهای مشکل‌دار: {', '.join(problems)})."
            continue
        if use_cache:
            db.set_ai_cache(sig, payload)
        return _payload_to_scores(payload, criteria_ids), None

    return {}, last_error or "تحلیل AI برای این Case ناموفق بود."


def _payload_to_scores(payload: dict, criteria_ids: list[str]) -> dict[str, tuple[float, str]]:
    criteria = payload.get("criteria", {})
    scores = payload.get("scores", {})
    evidence = payload.get("evidence", {})
    return {
        cid: (
            float(criteria[cid]["score"]) if cid in criteria else float(scores[cid]),
            _format_evidence(
                criteria[cid].get("evidence", ""),
                criteria[cid].get("source_events", []),
            ) if cid in criteria else str(evidence.get(cid, "")),
        )
        for cid in criteria_ids
        if (
            (cid in criteria and isinstance(criteria[cid], dict)
             and isinstance(criteria[cid].get("score"), (int, float)))
            or (cid in scores and isinstance(scores[cid], (int, float)))
        )
    }


def _format_evidence(evidence, source_events) -> str:
    if isinstance(evidence, dict):
        text = evidence.get("text") or evidence.get("fact") or str(evidence)
    else:
        text = str(evidence or "")
    if source_events:
        return f"{text} | رویدادهای مبنا: {source_events}"
    return text


def analyze_cases(
    cases: dict[str, CaseBundle],
    config: CriteriaConfig,
    settings: AISettings,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[str, dict[str, tuple[float, str]]], dict[str, str]]:
    """تحلیل AI برای مجموعه‌ای از Caseها. اگر AI غیرفعال باشد، دیکشنری خالی برمی‌گردد
    و بقیه Pipeline بدون AI (فقط Rule-Based) ادامه پیدا می‌کند."""
    if not settings.enabled or not settings.api_key:
        return {}, {}

    ai_criteria = [c for cat, c in config.active_criteria() if c.evaluation_type in ("AI", "HYBRID")]
    results: dict[str, dict[str, tuple[float, str]]] = {}
    errors: dict[str, str] = {}
    items = list(cases.items())
    total = len(items)
    for i, (key, case) in enumerate(items):
        if progress_cb:
            progress_cb(i, total, key)
        scores, error = analyze_case(case, ai_criteria, settings)
        if scores:
            results[key] = scores
        if error:
            errors[key] = error
    if progress_cb:
        progress_cb(total, total, "")
    return results, errors
