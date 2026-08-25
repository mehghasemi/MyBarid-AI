from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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
class CriteriaConfig:
    objective_ai_ratio: dict
    categories: list[Category]
    data_health_checks: list[dict]

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
    return CriteriaConfig(
        objective_ai_ratio=raw["objective_ai_ratio"],
        categories=categories,
        data_health_checks=raw["data_health_checks"],
    )


def save_criteria_config(config: CriteriaConfig, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
