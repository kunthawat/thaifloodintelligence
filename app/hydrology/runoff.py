"""Effective rainfall with explicit unit and evidence checks."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class RunoffInput:
    rainfall: float | None
    rainfall_unit: str | None
    loss: float | None
    loss_unit: str | None
    rainfall_fresh: bool
    semantics_verified: bool
    loss_model_validated: bool


@dataclass(frozen=True)
class RunoffResult:
    effective_rainfall: float | None
    unit: str | None
    eligible: bool
    reason: str | None


def effective_rainfall(inputs: RunoffInput) -> RunoffResult:
    if inputs.rainfall is None or inputs.loss is None:
        return RunoffResult(None, None, False, "MISSING_RAINFALL_OR_LOSS")
    if not inputs.rainfall_fresh:
        return RunoffResult(None, None, False, "STALE_RAINFALL")
    if not inputs.semantics_verified:
        return RunoffResult(None, None, False, "SOURCE_SEMANTICS_UNVERIFIED")
    if not inputs.loss_model_validated:
        return RunoffResult(None, None, False, "INSUFFICIENT_CALIBRATION")
    if inputs.rainfall_unit != inputs.loss_unit or inputs.rainfall_unit is None:
        return RunoffResult(None, None, False, "UNIT_MISMATCH")
    if not isfinite(inputs.rainfall) or not isfinite(inputs.loss):
        return RunoffResult(None, None, False, "INVALID_RAINFALL_OR_LOSS")
    if inputs.rainfall < 0 or inputs.loss < 0:
        return RunoffResult(None, None, False, "INVALID_RAINFALL_OR_LOSS")
    return RunoffResult(max(inputs.rainfall - inputs.loss, 0.0), inputs.rainfall_unit, True, None)
