"""Canonical observation normalization and quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.observation import Observation

MISSING_SENTINELS = {"-999", "999999", "9999", "-", "", "null", "none"}


@dataclass(frozen=True)
class QualityPolicy:
    expected_unit: str | None = None
    expected_datum: str | None = None
    semantics_status: str = "UNVERIFIED"
    native_timezone: str | None = None
    freshness_warn_after_seconds: int | None = None
    freshness_reject_after_seconds: int | None = None
    valid_min: float | None = None
    valid_max: float | None = None


def normalize_observation(raw: dict[str, Any], policy: QualityPolicy, now: datetime | None = None) -> Observation:
    """Normalize one provider record without coercing missing values to zero."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    raw_value = raw.get("value")
    raw_text = str(raw_value).strip().lower() if raw_value is not None else "null"
    value: float | None
    if raw_text in MISSING_SENTINELS:
        value = None
        state = "MISSING"
        reasons = ["MISSING_SENTINEL"]
    else:
        try:
            if isinstance(raw_value, bool):
                raise ValueError("boolean is not a numeric observation")
            value = float(raw_value)
            if not isfinite(value):
                raise ValueError("non-finite numeric observation")
            state = "VALID_ZERO" if value == 0 else "VALID"
            reasons = []
        except (TypeError, ValueError):
            value = None
            state = "MISSING"
            reasons = ["NON_NUMERIC_VALUE"]

    observed_at = _timestamp(raw.get("observed_at"), policy.native_timezone)
    received_at = _timestamp(raw.get("received_at"), policy.native_timezone) or now
    if observed_at is None and state in {"VALID", "VALID_ZERO"}:
        state = "SUSPECT"
        reasons.append("INVALID_OBSERVATION_TIMESTAMP")
    if observed_at is not None and observed_at > now and state in {"VALID", "VALID_ZERO"}:
        state = "SUSPECT"
        reasons.append("FUTURE_OBSERVATION_TIMESTAMP")

    if value is not None and state in {"VALID", "VALID_ZERO"}:
        age_seconds = (now - observed_at).total_seconds() if observed_at else None
        reject_after = policy.freshness_reject_after_seconds
        warn_after = policy.freshness_warn_after_seconds
        if reject_after is not None and age_seconds is not None and age_seconds > reject_after:
            state = "STALE"
            reasons.append("FRESHNESS_REJECT_THRESHOLD_EXCEEDED")
        elif warn_after is not None and age_seconds is not None and age_seconds > warn_after:
            state = "SUSPECT"
            reasons.append("FRESHNESS_WARN_THRESHOLD_EXCEEDED")

        unit = raw.get("unit")
        datum = raw.get("datum")
        if policy.expected_unit is None:
            state = "SUSPECT"
            reasons.append("UNIT_VALIDATION_UNAVAILABLE")
        elif unit != policy.expected_unit:
            state = "SUSPECT"
            reasons.append("UNIT_MISMATCH")
        if policy.expected_datum and datum != policy.expected_datum:
            state = "SUSPECT"
            reasons.append("DATUM_MISMATCH")
        if policy.semantics_status != "VERIFIED":
            state = "SUSPECT"
            reasons.append("SOURCE_SEMANTICS_UNVERIFIED")
        if policy.valid_min is not None and value < policy.valid_min:
            state = "SUSPECT"
            reasons.append("BELOW_VALID_RANGE")
        if policy.valid_max is not None and value > policy.valid_max:
            state = "SUSPECT"
            reasons.append("ABOVE_VALID_RANGE")

    usable = state in {"VALID", "VALID_ZERO"}
    return Observation(
        entity_id=str(raw.get("entity_id", "")),
        variable=str(raw.get("variable", "")),
        value=value,
        unit=raw.get("unit"),
        datum=raw.get("datum"),
        observed_at=observed_at.isoformat() if observed_at else None,
        received_at=received_at.isoformat(),
        source_id=str(raw.get("source_id", "")),
        source_record_id=str(raw.get("source_record_id", "")),
        quality_state=state,
        quality_score=1.0 if usable else (0.0 if value is None else 0.25),
        observation_type=str(raw.get("observation_type", "OBSERVED")),
        quality_reasons=reasons,
    )


def _timestamp(value: Any, native_timezone: str | None = None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        if not native_timezone:
            return None
        try:
            dt = dt.replace(tzinfo=ZoneInfo(native_timezone))
        except ZoneInfoNotFoundError:
            return None
    return dt.astimezone(timezone.utc)
