"""Conservative effective-capacity calculation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class EffectiveCapacity:
    value: float | None
    eligible: bool
    reason: str | None
    uncertainty: str


def effective_capacity(
    design_capacity: float | None,
    availability: float | None,
    head_factor: float | None,
    blockage_factor: float | None,
    operation_factor: float | None,
    semantics_verified: bool,
    capacity_unit: str | None = None,
    expected_unit: str = "m3/s",
) -> EffectiveCapacity:
    """Return capacity only when the factors and units are verified.

    Unknown pump/gate states are not converted into zero or full availability.
    """
    factors = (availability, head_factor, blockage_factor, operation_factor)
    if not semantics_verified:
        return EffectiveCapacity(None, False, "SOURCE_SEMANTICS_UNVERIFIED", "HIGH")
    if capacity_unit != expected_unit:
        return EffectiveCapacity(None, False, "SOURCE_SEMANTICS_UNVERIFIED", "HIGH")
    if design_capacity is None or any(value is None for value in factors):
        return EffectiveCapacity(None, False, "CONTROL_STATE_TOO_UNCERTAIN", "HIGH")
    if not isfinite(design_capacity) or any(not isfinite(value) for value in factors if value is not None):
        return EffectiveCapacity(None, False, "INVALID_CAPACITY_FACTOR", "HIGH")
    if design_capacity < 0 or any(value < 0 or value > 1 for value in factors if value is not None):
        return EffectiveCapacity(None, False, "INVALID_CAPACITY_FACTOR", "HIGH")
    capacity = design_capacity
    for factor in factors:
        capacity *= factor  # type: ignore[operator]
    return EffectiveCapacity(capacity, True, None, "LOW")
