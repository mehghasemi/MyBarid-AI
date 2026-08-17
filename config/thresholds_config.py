from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "thresholds.json"


@dataclass
class Thresholds:
    first_response_hours: dict = field(default_factory=lambda: {"excellent": 4, "good": 24, "acceptable": 72})
    due_date_grace_hours: float = 24
    followup_grace_days: dict = field(default_factory=lambda: {"good": 1, "acceptable": 3})
    unusual_gap_days: dict = field(default_factory=lambda: {"open_case": 14, "closed_case": 30})
    wait_status_reasons: list = field(default_factory=lambda: [
        "Waiting for Customer", "Waiting for Third Party", "On Hold", "Suspended",
    ])

    def to_dict(self) -> dict:
        return {
            "first_response_hours": self.first_response_hours,
            "due_date_grace_hours": self.due_date_grace_hours,
            "followup_grace_days": self.followup_grace_days,
            "unusual_gap_days": self.unusual_gap_days,
            "wait_status_reasons": self.wait_status_reasons,
        }


def load_thresholds(path: str | Path | None = None) -> Thresholds:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return Thresholds()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return Thresholds(**raw)


def save_thresholds(t: Thresholds, path: str | Path) -> None:
    Path(path).write_text(json.dumps(t.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


# نمونه فعال سراسری (Runtime قابل جایگزینی، مثلاً بعد از Import تنظیمات کاربر)
_active_thresholds: Thresholds | None = None


def get_thresholds() -> Thresholds:
    global _active_thresholds
    if _active_thresholds is None:
        _active_thresholds = load_thresholds()
    return _active_thresholds


def set_thresholds(t: Thresholds) -> None:
    global _active_thresholds
    _active_thresholds = t
