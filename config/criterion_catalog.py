"""Machine-readable criterion identities; no guessed business thresholds."""
from analysis.management import METRICS, SCHEMA_VERSION


def criterion_catalog(config, thresholds=None):
    thresholds = thresholds or {}
    rows = []
    for key, (name, source) in METRICS.items():
        count = key in {"status_entries", "reopens", "owner_changes"}
        rows.append({
            "id": key, "name": name, "version": SCHEMA_VERSION,
            "category": "quantitative", "definition": name,
            "management_use": "پیداکردن تأخیر، توقف یا کمبود داده با شاهد",
            "data_source": source, "method": "analysis.management.evaluate_case",
            "unit": "بار" if count else "ساعت تقویمی", "desired_direction": "lower",
            "threshold": thresholds.get(key), "weight": None,
            "applicability": "فقط موارد منتخب با داده معتبر و کامل موردنیاز",
            "missing_data": "insufficient_data", "severity": "warning",
            "required_evidence": source,
        })
    for category in config.categories:
        for item in category.criteria:
            rows.append({
                "id": item.id, "name": item.name_fa, "version": SCHEMA_VERSION,
                "category": "qualitative" if item.evaluation_type == "AI" else "rule",
                "definition": item.description_fa, "management_use": item.goal_fa,
                "data_source": "Note/Task دارای شناسه واقعی",
                "method": item.calculation_fa, "unit": "امتیاز از ۱۰۰",
                "desired_direction": "higher", "threshold": item.pass_threshold,
                "weight": item.weight, "active": item.active,
                "applicability": "پروفایل سرویس و شرایط مورد؛ نتیجه نهایی از مورد باز مطالبه نشود",
                "missing_data": "insufficient_data", "severity": "warning",
                "required_evidence": "ارجاع معتبر به Note/Task و توضیح مبتنی بر شاهد",
                "limitations": item.limitations_fa,
            })
    return rows
