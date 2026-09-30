"""Cross-border catchment attributes; national boundaries do not clip basins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CatchmentAttributes:
    catchment_id: str
    area_km2: float | None = None
    mean_elevation_m: float | None = None
    relief_m: float | None = None
    mean_slope: float | None = None
    max_slope: float | None = None
    flow_length_km: float | None = None
    time_of_concentration_seconds: float | None = None
    drainage_density: float | None = None
    soil_attributes: dict[str, Any] | None = None
    land_use_attributes: dict[str, Any] | None = None
    forest_cover: float | None = None
    flash_flood_susceptibility: float | None = None
    terrain_source: str | None = None
    terrain_quality_tier: str | None = None
    contributing_countries: tuple[str, ...] = ()
