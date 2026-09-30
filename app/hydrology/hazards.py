"""Frozen hazard taxonomy."""

from enum import StrEnum


class HazardType(StrEnum):
    RIVER_OVERFLOW = "RIVER_OVERFLOW"
    FLASH_FLOOD = "FLASH_FLOOD"
    LOCAL_RAIN = "LOCAL_RAIN"
    COASTAL_TIDAL = "COASTAL_TIDAL"
    COMPOUND = "COMPOUND"
