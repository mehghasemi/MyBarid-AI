from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "default_criteria.json"


@dataclass
class Criterion:
    id: str
    name_fa: str
    description_fa: str
    weight: float
    active: bool
    evaluation_type: str  # RULE | AI | HYBRID
    min_score: float = 0
    max_score: float = 100
    unit: str = "case"  # "case" (کارشناسان Help Desk) | "task" (کارشناسان پشتیبانی فنی)


@dataclass
class Category:
    id: str
    name_fa: str
    criteria: list[Criterion]


@dataclass
class CriteriaConfig:
    objective_ai_ratio: dict  # {"objective": .., "ai": ..}
    categories: list[Category]
    data_health_checks: list[dict]

    def active_criteria(self, unit: str | None = None):
        for cat in self.categories:
            for c in cat.criteria:
                if not c.active:
                    continue
                if unit is not None and c.unit != unit:
                    continue
                yield cat, c

    def normalized_weights(self, evaluation_types: tuple[str, ...] | None = None,
                            unit: str | None = None) -> dict[str, float]:
        """وزن نرمال‌شده معیارهای فعال (مجموع = ۱). می‌توان نوع ارزیابی و واحد بررسی را فیلتر کرد."""
        items = [
            (c.id, c.weight)
            for cat, c in self.active_criteria(unit=unit)
            if evaluation_types is None or c.evaluation_type in evaluation_types
        ]
        total = sum(w for _, w in items)
        if total <= 0:
            return {cid: 0.0 for cid, _ in items}
        return {cid: w / total for cid, w in items}

    def find_criterion(self, criterion_id: str) -> Criterion | None:
        for cat in self.categories:
            for c in cat.criteria:
                if c.id == criterion_id:
                    return c
        return None

    def to_dict(self) -> dict:
        return {
            "objective_ai_ratio": self.objective_ai_ratio,
            "categories": [
                {"id": cat.id, "name_fa": cat.name_fa, "criteria": [asdict(c) for c in cat.criteria]}
                for cat in self.categories
            ],
            "data_health_checks": self.data_health_checks,
        }


def load_criteria_config(path: str | Path | None = None) -> CriteriaConfig:
    p = Path(path) if path else DEFAULT_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    categories = [
        Category(
            id=cat["id"],
            name_fa=cat["name_fa"],
            criteria=[Criterion(**c) for c in cat["criteria"]],
        )
        for cat in raw["categories"]
    ]
    return CriteriaConfig(
        objective_ai_ratio=raw["objective_ai_ratio"],
        categories=categories,
        data_health_checks=raw["data_health_checks"],
    )


def save_criteria_config(config: CriteriaConfig, path: str | Path) -> None:
    Path(path).write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
