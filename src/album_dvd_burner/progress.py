from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

ProgressCallback = Callable[[str, str, "ProgressState | None"], None]


@dataclass
class ProgressState:
    stage: str
    label: str
    current: int = 0
    total: int = 0

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return min(100, int(round(100 * self.current / self.total)))

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "label": self.label,
            "current": self.current,
            "total": self.total,
            "percent": self.percent,
        }


class ProgressTracker:
    def __init__(self, on_progress: ProgressCallback | None = None) -> None:
        self._on_progress = on_progress
        self.state = ProgressState(stage="idle", label="Idle")

    def log(self, stage: str, message: str) -> None:
        if self._on_progress:
            self._on_progress(stage, message, self.state)

    def set_stage(self, stage: str, label: str, *, total: int) -> None:
        self.state = ProgressState(stage=stage, label=label, current=0, total=total)
        self.log(stage, label)

    def advance(self, stage: str, message: str, *, step: int = 1) -> None:
        self.state.stage = stage
        self.state.current = min(self.state.total, self.state.current + step)
        self.log(stage, message)

    def set(self, stage: str, message: str, *, current: int) -> None:
        self.state.stage = stage
        self.state.current = min(self.state.total, current)
        self.log(stage, message)
