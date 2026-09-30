"""Floodplain storage-state transitions preserve filling/draining hysteresis."""

from __future__ import annotations

from enum import StrEnum


class FloodplainState(StrEnum):
    DRY = "DRY"
    FILLING = "FILLING"
    CONNECTED = "CONNECTED"
    DRAINING = "DRAINING"
    ISOLATED_PONDING = "ISOLATED_PONDING"


def next_floodplain_state(
    previous: FloodplainState,
    *,
    channel_overflowing: bool,
    hydraulic_connection: bool,
    water_remains: bool,
    level_falling: bool,
) -> FloodplainState:
    """Use connectivity and prior state; falling stage does not imply dry land."""
    if previous == FloodplainState.ISOLATED_PONDING and water_remains:
        return FloodplainState.ISOLATED_PONDING
    if channel_overflowing and hydraulic_connection:
        return FloodplainState.FILLING
    if hydraulic_connection and water_remains and level_falling:
        return FloodplainState.DRAINING
    if hydraulic_connection and water_remains:
        return FloodplainState.CONNECTED
    if water_remains and not hydraulic_connection:
        return FloodplainState.ISOLATED_PONDING
    if previous in {FloodplainState.CONNECTED, FloodplainState.FILLING, FloodplainState.DRAINING} and not water_remains:
        return FloodplainState.DRY
    if channel_overflowing:
        return FloodplainState.FILLING
    return FloodplainState.DRY
