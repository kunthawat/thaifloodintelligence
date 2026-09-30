"""Canonical observation record."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Observation:
    entity_id: str
    variable: str
    value: float | None
    unit: str | None
    datum: str | None
    observed_at: str | None
    received_at: str
    source_id: str
    source_record_id: str
    quality_state: str
    quality_score: float
    observation_type: str
    quality_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
