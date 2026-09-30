"""Calibrated travel-time distributions, never one universal reach lag."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TravelTimeDistribution:
    p10_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None
    calibration_event_count: int
    calibration_valid: bool
    method: str

    @property
    def eligible(self) -> bool:
        values = (self.p10_seconds, self.p50_seconds, self.p90_seconds)
        return (
            self.calibration_valid
            and self.calibration_event_count > 0
            and all(value is not None and value >= 0 for value in values)
            and self.p10_seconds <= self.p50_seconds <= self.p90_seconds  # type: ignore[operator]
        )

    @property
    def reason(self) -> str | None:
        return None if self.eligible else "INSUFFICIENT_CALIBRATION"
