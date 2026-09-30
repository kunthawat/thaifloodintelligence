"""Location and hazard specific evidence gates; no synthetic flood probabilities."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from app.settings import configured_database_url

from app.services.admin_scope import location_admin, scoped_warnings
from app.services.rainfall_live import _read_cache as cached_rain
from app.services.waterlevel_live import _read_cache as cached_stage

HAZARDS = ("river_overflow", "flash_flood", "local_rain", "coastal_tidal", "compound")


def _age_hours(value: str | None) -> float | None:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600)
    except ValueError:
        return None


def _distance_km(lat: float, lon: float, row: dict) -> float:
    return math.hypot((row["lat"] - lat) * 111.0,
                      (row["lon"] - lon) * 111.0 * math.cos(math.radians(lat)))


def _nearby(cache: dict | None, lat: float, lon: float, maximum_km: float) -> list[dict]:
    if not cache or _age_hours(cache.get("fetched_at")) is None or _age_hours(cache.get("fetched_at")) > 24:
        return []
    rows = []
    for row in cache.get("stations", []):
        try:
            observed = datetime.fromisoformat(row.get("observed_at_source") or "")
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
            observation_age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds() / 3600
            if observation_age < -1 or observation_age > 6:
                continue
        except ValueError:
            continue
        distance = _distance_km(lat, lon, row)
        if distance <= maximum_km:
            rows.append({**row, "distance_km_approx": round(distance, 1)})
    return sorted(rows, key=lambda item: item["distance_km_approx"])[:5]


def _result(status: str, reasons: list[str], evidence: list[dict] | None = None) -> dict:
    return {"status": status, "reasons": reasons, "evidence": evidence or []}


def _same_catchment_stations(catchment: dict | None, stations: list[dict]) -> list[dict]:
    if not catchment or not stations or not configured_database_url():
        return []
    try:
        with psycopg.connect(configured_database_url(), connect_timeout=3) as connection, connection.cursor() as cursor:
            result = []
            for station in stations:
                cursor.execute("""SELECT ST_Covers(geom,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                                  FROM catchments WHERE catchment_id=%s""",
                               (station["lon"], station["lat"], catchment["catchment_id"]))
                row = cursor.fetchone()
                if row and row[0]:
                    result.append(station)
            return result
    except psycopg.Error:
        return []


def location_readiness(lat: float, lon: float, catchment: dict | None = None) -> dict[str, Any]:
    admin = location_admin(lat, lon)
    warnings = scoped_warnings(lat, lon)
    stage_cache = cached_stage()
    rain_cache = cached_rain()
    stage = _nearby(stage_cache, lat, lon, 20)
    rain = _nearby(rain_cache, lat, lon, 20)
    usable_stage = [row for row in stage if row.get("waterlevel_msl_m") is not None or
                    row.get("waterlevel_station_m") is not None]
    basin_stage = _same_catchment_stations(catchment, usable_stage)
    measured_rain = [row for row in rain if row.get("rain_1h_mm") is not None]
    basin_rain = _same_catchment_stations(catchment, measured_rain)
    positive_rain = [row for row in basin_rain if row["rain_1h_mm"] > 0]
    river_warning = []
    flash_warning = []
    coastal_warning = []
    for item in warnings["items"]:
        message = " ".join(str(item.get(key) or "") for key in ("title", "message", "hazard_type"))
        basis = item.get("warning_basis")
        if basis == "น้ำฝน" or any(word in message for word in ("น้ำป่า", "ดินถล่ม", "น้ำหลาก")):
            flash_warning.append(item)
        if basis == "ระดับน้ำ" or any(word in message for word in ("น้ำล้น", "ล้นตลิ่ง", "น้ำท่วม", "แม่น้ำ", "คลอง")):
            river_warning.append(item)
        if any(word in message for word in ("น้ำทะเล", "น้ำขึ้น", "คลื่นลม", "น้ำหนุน")):
            coastal_warning.append(item)

    def warning_status(items: list[dict]) -> str:
        if not items:
            return "NOT_READY"
        return "READY" if any(_age_hours(item.get("issued_at")) is not None and
                              ((_age_hours(item.get("issued_at")) <= 2) or
                               (item.get("valid_to") and _age_hours(item.get("issued_at")) <= 24))
                              for item in items) else "PARTIAL"

    if river_warning:
        river = _result(warning_status(river_warning), ["SCOPED_OFFICIAL_WARNING"], river_warning)
    elif basin_stage:
        river = _result("PARTIAL", ["SAME_CATCHMENT_STAGE", "HYDRAULIC_LINK_UNVERIFIED",
                                     "DATUM_OR_TIMEZONE_UNVERIFIED"],
                        [{"source": "ThaiWater", "station_id": row["station_id"],
                          "distance_km_approx": row["distance_km_approx"]} for row in basin_stage])
    else:
        river = _result("NOT_READY", ["NO_CONNECTED_STAGE_OR_SCOPED_WARNING"],
                        [{"source": "ThaiWater", "station_id": row["station_id"],
                          "distance_km_approx": row["distance_km_approx"],
                          "context_only": True} for row in usable_stage])
    flash = (_result(warning_status(flash_warning), ["SCOPED_OFFICIAL_WARNING"], flash_warning)
             if flash_warning else
             _result("PARTIAL", ["CATCHMENT_RAIN_OBSERVED", "RAIN_TRIGGER_THRESHOLD_UNVERIFIED",
                                  "WETNESS_AND_TIMEZONE_UNVERIFIED"],
                     [{"source": "ThaiWater", "station_id": row["station_id"], "rain_1h_mm": row["rain_1h_mm"]} for row in positive_rain])
             if positive_rain and catchment else _result("NOT_READY", ["NO_SCOPED_WARNING_OR_VERIFIED_RAIN_TRIGGER"]))
    local_rain = (_result("PARTIAL", ["NEARBY_RAIN_STATION", "OBSERVATION_TIMEZONE_UNVERIFIED"],
                          [{"source": "ThaiWater", "station_id": row["station_id"], "rain_1h_mm": row["rain_1h_mm"]} for row in measured_rain])
                  if measured_rain else _result("NOT_READY", ["NO_NEARBY_RAIN_OBSERVATION"]))
    coastal = (_result(warning_status(coastal_warning), ["SCOPED_COASTAL_WARNING"], coastal_warning)
               if coastal_warning else _result("NOT_READY", ["NO_VERIFIED_COASTAL_BOUNDARY_OR_TIDE_EVIDENCE"]))
    processes = [row for row in (river, flash, coastal) if row["status"] in ("READY", "PARTIAL")]
    compound = (_result("PARTIAL", ["MULTIPLE_PROCESSES_WITH_INCOMPLETE_LINKAGE"])
                if len(processes) >= 2 else _result("NOT_READY", ["FEWER_THAN_TWO_SUPPORTED_PROCESSES"]))
    hazards = dict(zip(HAZARDS, (river, flash, local_rain, coastal, compound)))
    relevant = (river, flash, coastal, compound)
    overall = "READY" if any(row["status"] == "READY" for row in relevant) else \
              "PARTIAL" if any(row["status"] == "PARTIAL" for row in relevant) else "NOT_READY"
    return {"location": {"latitude": lat, "longitude": lon}, "admin": admin or None,
            "overall": overall, "hazards": hazards, "official_warnings": warnings,
            "outputs": {"hazard_assessment": overall == "READY", "flood_probability": False,
                        "peak_height": False, "arrival_time": False, "point_depth": False},
            "limitations": ["NEARBY_STATION_NOT_HYDROLOGIC_CONNECTION"] if usable_stage and not basin_stage else
                           ["SAME_CATCHMENT_NOT_VERIFIED_REACH_LINK"] if basin_stage else [],
            "generated_at": datetime.now(timezone.utc).isoformat()}
