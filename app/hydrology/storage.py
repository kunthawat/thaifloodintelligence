"""Mass balance and storage-stage safeguards."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class StorageUpdate:
    storage_next_m3: float | None
    eligible: bool
    reason: str | None


def mass_balance_step(
    *, storage_m3: float | None, qin_m3s: float | None, qout_m3s: float | None,
    timestep_seconds: float | None, inputs_verified: bool,
) -> StorageUpdate:
    if not inputs_verified:
        return StorageUpdate(None, False, "SOURCE_SEMANTICS_UNVERIFIED")
    if None in (storage_m3, qin_m3s, qout_m3s, timestep_seconds):
        return StorageUpdate(None, False, "INSUFFICIENT_VALID_OBSERVATIONS")
    assert storage_m3 is not None and qin_m3s is not None and qout_m3s is not None and timestep_seconds is not None
    if any(not isfinite(value) for value in (storage_m3, qin_m3s, qout_m3s, timestep_seconds)):
        return StorageUpdate(None, False, "INVALID_STORAGE_INPUT")
    if timestep_seconds <= 0 or storage_m3 < 0:
        return StorageUpdate(None, False, "INVALID_STORAGE_INPUT")
    updated = storage_m3 + (qin_m3s - qout_m3s) * timestep_seconds
    if updated < 0:
        return StorageUpdate(None, False, "MASS_BALANCE_OUT_OF_RANGE")
    return StorageUpdate(updated, True, None)


def stage_from_storage(
    storage_m3: float | None,
    points: list[tuple[float, float]] | None,
    *,
    curve_validated: bool,
    datum: str | None,
    storage_unit: str = "m3",
    stage_unit: str = "m",
) -> tuple[float | None, str | None]:
    """Interpolate a verified S(H) curve; storage alone never implies stage."""
    if not curve_validated or not points or not datum or storage_unit != "m3" or stage_unit != "m":
        return None, "NO_VALID_STAGE_STORAGE_MODEL"
    if storage_m3 is None or not isfinite(storage_m3) or any(not all(map(_finite, pair)) for pair in points):
        return None, "NO_VALID_STAGE_STORAGE_MODEL"
    ordered = sorted(points, key=lambda point: point[0])
    if len(ordered) < 2 or any(
        ordered[i][0] >= ordered[i + 1][0] or ordered[i][1] >= ordered[i + 1][1]
        for i in range(len(ordered) - 1)
    ):
        return None, "NO_VALID_STAGE_STORAGE_MODEL"
    if storage_m3 < ordered[0][0] or storage_m3 > ordered[-1][0]:
        return None, "NO_VALID_STAGE_STORAGE_MODEL"
    for (s0, h0), (s1, h1) in zip(ordered, ordered[1:]):
        if s0 <= storage_m3 <= s1:
            fraction = (storage_m3 - s0) / (s1 - s0)
            return h0 + fraction * (h1 - h0), None
    return None, "NO_VALID_STAGE_STORAGE_MODEL"


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
