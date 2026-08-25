from __future__ import annotations

import hashlib
import json
import time
from typing import Callable

from ai.prompts import build_case_prompt, build_system_prompt
from ai.providers import AIProviderError, AISettings, get_provider
from ai.schemas import extract_json, validate_case_analysis
from config.criteria_config import CriteriaConfig
from data.cleaner import CaseBundle
from database import db

MAX_RETRIES = 2


def _case_signature(case: CaseBundle, ai_criteria, settings: AISettings) -> str:
    criteria_fingerprint = repr([
        (c.id, c.name_fa, c.evaluation_type, getattr(c, "prompt_fa", None),
         getattr(c, "description_fa", None))
        for c in ai_criteria
    ])
    # Do not include the API key, but invalidate old results when any
    # provider/prompt-affecting setting changes.
    settings_fingerprint = repr((
        settings.provider, settings.model, settings.base_url,
        settings.temperature, settings.max_tokens,
    ))
    parts = [case.case_key, criteria_fingerprint, settings_fingerprint]
    for n in case.notes:
        parts.append(f"N|{n.note_date}|{n.description}")
    for t in case.tasks:
        parts.append(f"T|{t.created_on}|{t.description}")
    raw = "\n".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def analyze_case(
    case: CaseBundle, ai_criteria, settings: AISettings, use_cache: bool = True,
    force: bool = False,
) -> tuple[dict[str, tuple[float, str]], str | None]:
    """یک Case را تحلیل می‌کند. خروجی: (scores_by_criterion, error_message).
    اگر AI شکست بخورد، دیکشنری خالی برمی‌گردد و پیام خطا پر می‌شود؛ هرگز امتیاز جعلی تولید نمی‌شود."""
    criteria_ids = [c.id for c in ai_criteria]
    if not criteria_ids:
        return {}, None

    sig = _case_signature(case, ai_criteria, settings)
    if use_cache and not force:
        try:
            cached = db.get_ai_cache(sig)
            if cached:
                cached_scores = _payload_to_scores(cached, criteria_ids)
                if cached_scores:
                    return cached_scores, None
                # Cache قدیمی/ناقص نباید به‌عنوان تحلیل موفق تلقی شود.
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            # A corrupt/old cache entry must not abort the whole dataset.
            last_error = f"Cache پاسخ AI قابل استفاده نبود؛ درخواست جدید ارسال شد: {exc}"

    try:
        provider = get_provider(settings)
    except Exception as exc:  # noqa: BLE001
        return {}, f"Provider AI قابل استفاده نیست: {exc}"
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
        try:
            payload = extract_json(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = f"پاسخ AI قابل پردازش نبود: {exc}"
            continue
        if payload is None:
            last_error = "خروجی AI یک JSON معتبر نبود."
            continue
        try:
            valid, problems = validate_case_analysis(payload, criteria_ids)
        except Exception as exc:  # noqa: BLE001
            last_error = "ساختار پاسخ AI قابل بررسی نبود؛ پاسخ معتبر برای معیارها دریافت نشد."
            continue
        if not valid:
            last_error = f"خروجی AI ناقص بود (فیلدهای مشکل‌دار: {', '.join(problems)})."
            continue
        try:
            scores = _payload_to_scores(payload, criteria_ids)
            if not scores:
                last_error = "پاسخ سرویس AI برای هیچ‌یک از معیارهای فعال امتیاز معتبر برنگرداند."
                continue
            if use_cache:
                db.set_ai_cache(sig, payload)
            return scores, None
        except (AttributeError, KeyError, TypeError, ValueError, IndexError) as exc:
            last_error = f"ساختار امتیازهای AI قابل استفاده نبود: {exc}"
            continue

    return {}, last_error or "تحلیل AI برای این Case ناموفق بود."


def is_case_ai_analyzed(
    case: CaseBundle, config: CriteriaConfig, settings: AISettings,
) -> bool:
    """Whether a successful cached AI result exists for this case/settings."""
    if not settings.enabled or not settings.api_key:
        return False
    ai_criteria = [
        c for _, c in config.active_criteria()
        if c.evaluation_type in ("AI", "HYBRID")
    ]
    if not ai_criteria:
        return False
    try:
        cached = db.get_ai_cache(_case_signature(case, ai_criteria, settings))
        return bool(cached and _payload_to_scores(cached, [c.id for c in ai_criteria]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _payload_to_scores(payload: dict, criteria_ids: list[str]) -> dict[str, tuple[float, str]]:
    if not isinstance(payload, dict):
        return {}
    criteria = payload.get("criteria")
    scores = payload.get("scores")
    evidence = payload.get("evidence")
    criteria = criteria if isinstance(criteria, dict) else {}
    scores = scores if isinstance(scores, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    result = {}
    for cid in criteria_ids:
        item = criteria.get(cid)
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
            result[cid] = (
                float(item["score"]),
                _format_evidence(item.get("evidence", ""), item.get("source_events", [])),
            )
        elif isinstance(scores.get(cid), (int, float)):
            result[cid] = (float(scores[cid]), str(evidence.get(cid, "")))
    return result


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
    force: bool = False,
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
        try:
            scores, error = analyze_case(case, ai_criteria, settings, force=force)
        except Exception as exc:  # noqa: BLE001
            # One malformed provider/cache response must not stop all cases.
            scores, error = {}, f"خطای کنترل‌نشده AI برای این مورد: {exc}"
        if scores:
            results[key] = scores
        if error:
            errors[key] = error
    if progress_cb:
        progress_cb(total, total, "")
    return results, errors
