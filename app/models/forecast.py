"""Forecast contract built from verified readiness/evidence without fake precision."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _output(eligible: bool, reason: str | None, *, value: Any = None) -> dict[str, Any]:
    return {"value": value, "eligible": eligible, "reason": reason}


def _evidence_codes(readiness: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for hazard in (readiness.get("hazards") or {}).values():
        for reason in hazard.get("reasons") or []:
            if reason not in codes:
                codes.append(reason)
    for reason in readiness.get("limitations") or []:
        if reason not in codes:
            codes.append(reason)
    return codes


def build_forecast(location: dict[str, float], readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return an eligibility-aware forecast using current evidence only.

    Readiness/evidence can support a situation report while quantitative outputs
    remain unavailable.  This function deliberately never invents probability,
    ETA, peak height, duration, or point depth.
    """
    readiness = readiness or {}
    overall = readiness.get("overall", "NOT_READY")
    mode = readiness.get("mode", "NO_EVIDENCE")
    hazards = readiness.get("hazards") or {}
    evidence_codes = _evidence_codes(readiness)
    active_supported = [name for name, row in hazards.items() if row.get("status") in {"READY", "PARTIAL"}]

    occurrence_reason = (
        "INSUFFICIENT_CALIBRATION" if active_supported else
        "INSUFFICIENT_VALID_OBSERVATIONS"
    )
    data_state = "EVIDENCE_ONLY" if mode in {"EVIDENCE_ONLY", "HAZARD_EVIDENCE"} else "INSUFFICIENT_DATA"

    confidence = {
        "occurrence": "LOW" if active_supported else "UNAVAILABLE",
        "arrival": "UNAVAILABLE",
        "bankfull": "UNAVAILABLE",
        "peak_height": "UNAVAILABLE",
        "duration": "UNAVAILABLE",
        "location_exposure": "UNAVAILABLE",
        "point_depth": "UNAVAILABLE",
    }

    warning = readiness.get("official_warnings") or {"available": False, "items": []}
    return {
        "location": location,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hazard": None,
        "overall_probability": None,
        "will_flood": _output(False, occurrence_reason),
        "occurrence": _output(False, occurrence_reason),
        "first_impact": {"eligible": False, "p50_hours": None, "range_hours": None, "reason": "EVENT_DATA_UNAVAILABLE"},
        "time_to_bankfull": {"eligible": False, "range_hours": None, "reason": "BANK_REFERENCE_UNAVAILABLE"},
        "peak_above_bank_m": _output(False, "NO_VALID_STAGE_STORAGE_MODEL"),
        "time_to_peak": _output(False, "NO_VALID_STAGE_STORAGE_MODEL"),
        "duration_above_bank": _output(False, "NO_VALID_STAGE_STORAGE_MODEL"),
        "location_exposure": _output(False, "TERRAIN_OR_CONNECTIVITY_NOT_VALIDATED"),
        "point_depth": _output(False, "POINT_CONNECTIVITY_UNCERTAIN"),
        "active_waves": None,
        "event_status": None,
        "risk_drivers": evidence_codes,
        "risk_reducers": [],
        "uncertainties": list(dict.fromkeys(evidence_codes + [occurrence_reason])),
        "confidence": confidence,
        "official_warning": warning,
        "recommended_timeline": [],
        "data_state": data_state,
        "readiness": {"overall": overall, "mode": mode, "hazards": hazards},
    }
