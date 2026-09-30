"""Boundary signals stay separate until a verified inland propagation model is available."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Callable


@dataclass(frozen=True)
class TideComponents:
    astronomical_tide: float | None
    observed_sea_level: float | None
    surge_residual: float | None
    unit: str | None
    datum: str | None
    observed_at: str | None
    semantics_verified: bool
    fresh: bool
    is_predicted_only: bool = False


@dataclass(frozen=True)
class InlandBoundaryStage:
    value: float | None
    unit: str | None
    datum: str | None
    eligible: bool
    confidence: str
    reason: str | None


PropagationModel = Callable[[TideComponents, str], tuple[float, str, str]]


def gate_downstream_stage(
    tide: TideComponents,
    *,
    river_path_id: str | None,
    propagation_model: PropagationModel | None,
    expected_unit: str | None = None,
    expected_datum: str | None = None,
) -> InlandBoundaryStage:
    """Use a validated estuary/river model; never pass sea tide directly to a gate."""
    if tide.unit is None or tide.datum is None or not tide.semantics_verified:
        return InlandBoundaryStage(None, None, None, False, "UNAVAILABLE", "SOURCE_SEMANTICS_UNVERIFIED")
    if not tide.fresh:
        return InlandBoundaryStage(None, None, None, False, "UNAVAILABLE", "DOWNSTREAM_BOUNDARY_UNCERTAIN")
    if not river_path_id or propagation_model is None:
        return InlandBoundaryStage(None, None, None, False, "UNAVAILABLE", "DOWNSTREAM_BOUNDARY_UNCERTAIN")
    if expected_unit is None or expected_datum is None:
        return InlandBoundaryStage(None, None, None, False, "UNAVAILABLE", "DOWNSTREAM_BOUNDARY_UNCERTAIN")
    try:
        stage, unit, datum = propagation_model(tide, river_path_id)
    except Exception:
        return InlandBoundaryStage(None, None, None, False, "UNAVAILABLE", "DOWNSTREAM_BOUNDARY_UNCERTAIN")
    if not isfinite(stage) or unit != expected_unit or datum != expected_datum:
        return InlandBoundaryStage(None, None, None, False, "UNAVAILABLE", "DOWNSTREAM_BOUNDARY_UNCERTAIN")
    if tide.is_predicted_only:
        return InlandBoundaryStage(stage, unit, datum, True, "LOW", None)
    return InlandBoundaryStage(stage, unit, datum, True, "MEDIUM", None)
