from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "v2_criteria.json"
GUIDE_PATH = Path(__file__).parent / "criteria_guides.json"


@dataclass
class Criterion:
    id: str
    name_fa: str
    description_fa: str
    weight: float
    active: bool
    evaluation_type: str
    min_score: float = 0
    max_score: float = 100
    unit: str = "case"
    layer: str = "performance"
    na_policy: str = "exclude"
    goal_fa: str = ""
    calculation_fa: str = ""
    interpretation_fa: str = ""
    example_fa: str = ""
    limitations_fa: str = ""


@dataclass
class Category:
    id: str
    name_fa: str
    criteria: list[Criterion]
    layer: str = "performance"
    weight: float = 0


@dataclass
class EvaluationProfile:
    id: str
    name_fa: str
    service_values: list[str]
    keywords: list[str]
    criteria_ids: list[str]


DEFAULT_EVALUATION_PROFILES = [
    EvaluationProfile(
        id="guidance",
        name_fa="راهنمایی و آموزش",
        service_values=["راهنمایی", "آموزش", "اطلاعات", "guidance", "how-to"],
        keywords=["راهنمایی", "آموزش", "نحوه", "how to", "راهنما"],
        criteria_ids=[
            "problem_understanding", "customer_interaction_quality",
            "conclusion_adequacy", "final_status_clear",
            "first_response_time", "notes_completeness", "notes_result_recorded",
        ],
    ),
    EvaluationProfile(
        id="incident",
        name_fa="رفع مشکل",
        service_values=["رفع مشکل", "incident", "problem", "break-fix"],
        keywords=["رفع مشکل", "خرابی", "قطعی", "خطا", "incident", "problem"],
        criteria_ids=[
            "problem_understanding", "solution_appropriateness",
            "customer_interaction_quality", "conclusion_adequacy",
            "final_status_clear", "first_response_time",
            "notes_completeness", "notes_result_recorded",
            "timeline_reconstructable",
        ],
    ),
    EvaluationProfile(
        id="request",
        name_fa="درخواست خدمت یا تغییر",
        service_values=["درخواست", "تغییر", "دسترسی", "request", "change"],
        keywords=["درخواست", "تغییر", "دسترسی", "request", "change"],
        criteria_ids=[
            "problem_understanding", "solution_appropriateness",
            "customer_interaction_quality", "conclusion_adequacy",
            "final_status_clear", "first_response_time",
            "task_presence_when_needed", "task_case_relation",
            "notes_completeness", "notes_result_recorded",
        ],
    ),
]


@dataclass
class CriteriaConfig:
    objective_ai_ratio: dict
    categories: list[Category]
    data_health_checks: list[dict]
    evaluation_profiles: list[EvaluationProfile] = field(default_factory=list)

    def active_criteria(self, unit: str | None = None):
        for cat in self.categories:
            for criterion in cat.criteria:
                if not criterion.active:
                    continue
                if unit is not None and criterion.unit != unit:
                    continue
                yield cat, criterion

    def normalized_weights(
        self,
        evaluation_types: tuple[str, ...] | None = None,
        unit: str | None = None,
    ) -> dict[str, float]:
        items = [
            (criterion.id, criterion.weight)
            for _, criterion in self.active_criteria(unit=unit)
            if evaluation_types is None or criterion.evaluation_type in evaluation_types
        ]
        total = sum(weight for _, weight in items)
        if total <= 0:
            return {criterion_id: 0.0 for criterion_id, _ in items}
        return {criterion_id: weight / total for criterion_id, weight in items}

    def find_criterion(self, criterion_id: str) -> Criterion | None:
        for category in self.categories:
            for criterion in category.criteria:
                if criterion.id == criterion_id:
                    return criterion
        return None

    def match_profile(self, case) -> EvaluationProfile | None:
        service = (getattr(case, "service", None) or "").strip().casefold()
        text = " ".join(filter(None, [
            getattr(case, "service", None),
            getattr(case, "case_title", None),
            getattr(case, "scenario", None),
            getattr(case, "case_description", None),
            getattr(case, "status_reason", None),
        ])).casefold()
        for profile in self.evaluation_profiles:
            if any(value.casefold() == service for value in profile.service_values if value):
                return profile
        for profile in self.evaluation_profiles:
            if any(keyword.casefold() in text for keyword in profile.keywords if keyword):
                return profile
        return None

    def criteria_for_case(self, case, unit: str | None = None):
        profile = self.match_profile(case)
        allowed = set(profile.criteria_ids) if profile else None
        for category, criterion in self.active_criteria(unit=unit):
            if allowed is None or criterion.id in allowed:
                yield category, criterion

    def to_dict(self) -> dict:
        return {
            "objective_ai_ratio": self.objective_ai_ratio,
            "categories": [
                {
                    "id": category.id,
                    "name_fa": category.name_fa,
                    "layer": category.layer,
                    "weight": category.weight,
                    "criteria": [asdict(criterion) for criterion in category.criteria],
                }
                for category in self.categories
            ],
            "data_health_checks": self.data_health_checks,
            "evaluation_profiles": [
                {
                    "id": profile.id, "name_fa": profile.name_fa,
                    "service_values": profile.service_values,
                    "keywords": profile.keywords,
                    "criteria_ids": profile.criteria_ids,
                }
                for profile in self.evaluation_profiles
            ],
        }


def load_criteria_config(path: str | Path | None = None) -> CriteriaConfig:
    config_path = Path(path) if path else DEFAULT_PATH
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    guides = {}
    if GUIDE_PATH.exists():
        try:
            guides = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            guides = {}
    categories = [
        Category(
            id=category["id"],
            name_fa=category["name_fa"],
            layer=category.get("layer", "performance"),
            weight=category.get("weight", 0),
            criteria=[
                Criterion(
                    id=criterion["id"],
                    name_fa=criterion["name_fa"],
                    description_fa=criterion["description_fa"],
                    weight=criterion["weight"],
                    active=criterion["active"],
                    evaluation_type=criterion["evaluation_type"],
                    min_score=criterion.get("min_score", 0),
                    max_score=criterion.get("max_score", 100),
                    unit=criterion.get("unit", "case"),
                    layer=criterion.get("layer", category.get("layer", "performance")),
                    na_policy=criterion.get("na_policy", "exclude"),
                    **guides.get(criterion["id"], {}),
                )
                for criterion in category["criteria"]
            ],
        )
        for category in raw["categories"]
    ]
    profiles = [
        EvaluationProfile(
            id=item["id"], name_fa=item["name_fa"],
            service_values=item.get("service_values", []),
            keywords=item.get("keywords", []),
            criteria_ids=item.get("criteria_ids", []),
        )
        for item in raw.get("evaluation_profiles", [])
    ] or DEFAULT_EVALUATION_PROFILES
    return CriteriaConfig(
        objective_ai_ratio=raw["objective_ai_ratio"],
        categories=categories,
        data_health_checks=raw["data_health_checks"],
        evaluation_profiles=profiles,
    )


def save_criteria_config(config: CriteriaConfig, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
