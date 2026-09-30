"""Forecast contract and per-output eligibility handling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _output(eligible: bool, reason: str | None) -> dict[str, Any]:
    return {
        "value": None,
        "eligible": eligible,
        "reason": reason,
    }


def build_forecast(location: dict[str, float]) -> dict[str, Any]:
    """Return an honest, fully shaped forecast when no verified inputs exist.

    Nulls are intentional: no provider, observations, catchment graph, or
    calibrated hydrologic model is configured in this initial project.
    """
    no_observations = "INSUFFICIENT_VALID_OBSERVATIONS"
    return {
        "location": location,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hazard": None,
        "overall_probability": None,
        "will_flood": _output(False, no_observations),
        "occurrence": _output(False, no_observations),
        "first_impact": {
            "eligible": False,
            "p50_hours": None,
            "range_hours": None,
            "reason": "EVENT_DATA_UNAVAILABLE",
        },
        "time_to_bankfull": {
            "eligible": False,
            "range_hours": None,
            "reason": "BANK_REFERENCE_UNAVAILABLE",
        },
        "peak_above_bank_m": {
            "eligible": False,
            "value": None,
            "reason": "NO_VALID_STAGE_STORAGE_MODEL",
        },
        "time_to_peak": {
            "eligible": False,
            "value": None,
            "reason": "NO_VALID_STAGE_STORAGE_MODEL",
        },
        "duration_above_bank": {
            "eligible": False,
            "value": None,
            "reason": "NO_VALID_STAGE_STORAGE_MODEL",
        },
        "location_exposure": {
            "eligible": False,
            "value": None,
            "reason": "TERRAIN_RESOLUTION_INSUFFICIENT",
        },
        "point_depth": {
            "eligible": False,
            "value": None,
            "reason": "POINT_CONNECTIVITY_UNCERTAIN",
        },
        "active_waves": None,
        "event_status": None,
        "risk_drivers": [],
        "risk_reducers": [],
        "uncertainties": [
            "SOURCE_NOT_CONFIGURED",
            "NETWORK_DATA_UNAVAILABLE",
            "INSUFFICIENT_VALID_OBSERVATIONS",
        ],
        "confidence": {
            "occurrence": "UNAVAILABLE",
            "arrival": "UNAVAILABLE",
            "bankfull": "UNAVAILABLE",
            "peak_height": "UNAVAILABLE",
            "duration": "UNAVAILABLE",
            "location_exposure": "UNAVAILABLE",
            "point_depth": "UNAVAILABLE",
        },
        "official_warning": {
            "available": False,
            "items": [],
            "reason": "SOURCE_NOT_CONFIGURED",
        },
        "recommended_timeline": [],
        "data_state": "INSUFFICIENT_DATA",
    }
