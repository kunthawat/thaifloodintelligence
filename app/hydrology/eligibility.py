"""Per-output forecast eligibility checks."""

from __future__ import annotations


def peak_height_eligibility(
    *, current_stage_fresh: bool, bank_reference_available: bool, bank_reference_in_scope: bool, stage_storage_valid: bool,
    controls_sufficiently_known: bool, boundary_sufficiently_known: bool,
) -> tuple[bool, str | None]:
    """Never provide a centimetre peak without the required physical chain."""
    if not current_stage_fresh:
        return False, "STALE_CURRENT_STAGE"
    if not bank_reference_available:
        return False, "BANK_REFERENCE_UNAVAILABLE"
    if not bank_reference_in_scope:
        return False, "BANK_REFERENCE_OUT_OF_SCOPE"
    if not stage_storage_valid:
        return False, "NO_VALID_STAGE_STORAGE_MODEL"
    if not controls_sufficiently_known:
        return False, "CONTROL_STATE_TOO_UNCERTAIN"
    if not boundary_sufficiently_known:
        return False, "DOWNSTREAM_BOUNDARY_UNCERTAIN"
    return True, None
