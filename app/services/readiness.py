"""Location/hazard readiness and situation reporting from available evidence.

This module deliberately separates:
- source health,
- current situation reporting,
- hazard readiness,
- quantitative forecast eligibility.

No synthetic flood probabilities are created here.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from app.settings import configured_database_url
from app.services.admin_scope import location_admin, scoped_warnings
from app.services.geography import hydraulic_station_links, river_route
from app.services.live_observation_ingest import canonical_nearby
from app.services.rainfall_live import _read_cache as cached_rain
from app.services.sources import cached_source_health
from app.services.waterlevel_live import _read_cache as cached_stage

HAZARDS = ("river_overflow", "flash_flood", "local_rain", "coastal_tidal", "compound")

# Used only to decide whether a tide source is geographically relevant.  This is not a
# flood-risk classification and does not replace hydraulic downstream-boundary mapping.
_COASTAL_PROVINCES = {
    "กรุงเทพมหานคร", "สมุทรปราการ", "สมุทรสาคร", "สมุทรสงคราม", "เพชรบุรี",
    "ประจวบคีรีขันธ์", "ชุมพร", "สุราษฎร์ธานี", "นครศรีธรรมราช", "สงขลา",
    "ปัตตานี", "นราธิวาส", "ชลบุรี", "ระยอง", "จันทบุรี", "ตราด", "ฉะเชิงเทรา",
    "ระนอง", "พังงา", "ภูเก็ต", "กระบี่", "ตรัง", "สตูล",
}


def _age_hours(value: str | None) -> float | None:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600)
    except (TypeError, ValueError):
        return None


def _distance_km(lat: float, lon: float, row: dict) -> float:
    return math.hypot((row["lat"] - lat) * 111.0,
                      (row["lon"] - lon) * 111.0 * math.cos(math.radians(lat)))


def _nearby(cache: dict | None, lat: float, lon: float, maximum_km: float,
            observation_max_age_hours: float = 2) -> list[dict]:
    # Stale station snapshots remain visible on the map, but they cannot support
    # a current situation or hazard assessment.
    if not cache or cache.get("stale"):
        return []
    fetch_age = _age_hours(cache.get("fetched_at"))
    if fetch_age is None or fetch_age > 24:
        return []
    rows = []
    for row in cache.get("stations", []):
        try:
            observed = datetime.fromisoformat(row.get("observed_at_source") or "")
            if observed.tzinfo is None:
                # ThaiWater public pages represent Thai station local time in practice,
                # but keep the reason visible until provider semantics are formally frozen.
                observed = observed.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
            observation_age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds() / 3600
            if observation_age < -1 or observation_age > observation_max_age_hours:
                continue
        except (TypeError, ValueError):
            continue
        distance = _distance_km(lat, lon, row)
        if distance <= maximum_km:
            rows.append({**row, "distance_km_approx": round(distance, 1)})
    return sorted(rows, key=lambda item: item["distance_km_approx"])[:8]


def _result(status: str, reasons: list[str], evidence: list[dict] | None = None) -> dict:
    return {"status": status, "reasons": reasons, "evidence": evidence or []}


def _same_catchment_stations(catchment: dict | None, stations: list[dict]) -> list[dict]:
    """Catchment membership is contextual evidence, not hydraulic connectivity."""
    if not catchment or not stations or not configured_database_url():
        return []
    try:
        with psycopg.connect(configured_database_url(), connect_timeout=3) as connection, connection.cursor() as cursor:
            result = []
            for station in stations:
                cursor.execute(
                    """SELECT ST_Covers(geom,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                       FROM catchments WHERE catchment_id=%s""",
                    (station["lon"], station["lat"], catchment["catchment_id"]),
                )
                row = cursor.fetchone()
                if row and row[0]:
                    result.append(station)
            return result
    except psycopg.Error:
        return []


def _warning_status(items: list[dict]) -> str:
    if not items:
        return "NOT_READY"
    for item in items:
        age = _age_hours(item.get("issued_at"))
        if age is not None and (age <= 2 or (item.get("valid_to") and age <= 24)):
            return "READY"
    return "PARTIAL"


def _classify_warnings(items: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    river_warning: list[dict] = []
    flash_warning: list[dict] = []
    coastal_warning: list[dict] = []
    for item in items:
        message = " ".join(str(item.get(key) or "") for key in ("title", "message", "hazard_type"))
        basis = item.get("warning_basis")
        if basis == "น้ำฝน" or any(word in message for word in ("น้ำป่า", "ดินถล่ม", "น้ำหลาก")):
            flash_warning.append(item)
        if basis == "ระดับน้ำ" or any(word in message for word in ("น้ำล้น", "ล้นตลิ่ง", "น้ำท่วม", "แม่น้ำ", "คลอง")):
            river_warning.append(item)
        if any(word in message for word in ("น้ำทะเล", "น้ำขึ้น", "คลื่นลม", "น้ำหนุน")):
            coastal_warning.append(item)
    return river_warning, flash_warning, coastal_warning


def _situation_status(*, warnings: dict, stage: list[dict], rain: list[dict], catchment: dict | None,
                      admin: dict | None) -> dict[str, Any]:
    current_warning_count = len(warnings.get("items") or [])
    history_count = len(warnings.get("historical_context") or [])
    fresh_measurements = bool(stage or rain)
    if current_warning_count or fresh_measurements:
        status = "READY"
    elif history_count or catchment or admin:
        status = "PARTIAL"
    else:
        status = "NOT_READY"
    return {
        "status": status,
        "ready": status != "NOT_READY",
        "mode": "OBSERVATION_AND_WARNING" if current_warning_count or fresh_measurements else
                "CONTEXT_ONLY" if status == "PARTIAL" else "NO_EVIDENCE",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "evidence": {
            "current_warning_count": current_warning_count,
            "historical_warning_count": history_count,
            "nearby_stage_count": len(stage),
            "nearby_rain_count": len(rain),
            "catchment_available": bool(catchment),
            "admin_scope_available": bool(admin),
        },
    }


def _ingested_tide_available() -> bool:
    """A reachable Navy index is not boundary evidence until predictions were parsed and stored."""
    if not configured_database_url():
        return False
    try:
        with psycopg.connect(configured_database_url(), connect_timeout=3) as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT EXISTS(
                SELECT 1 FROM observations
                WHERE source_id='navy_tide'
                  AND variable='PREDICTED_TIDE_LEVEL'
                  AND observation_type='FORECAST'
                  AND quality_state IN ('VALID','ESTIMATED')
                  AND observed_at BETWEEN now()-interval '12 hours' AND now()+interval '14 days'
            )""")
            return bool(cursor.fetchone()[0])
    except psycopg.Error:
        return False


def location_readiness(lat: float, lon: float, catchment: dict | None = None) -> dict[str, Any]:
    admin = location_admin(lat, lon)
    warnings = scoped_warnings(lat, lon)
    stage_cache = cached_stage()
    rain_cache = cached_rain()

    # Canonical observations are the system of record.  The file cache is only a
    # transport fallback during startup or a temporary database outage.
    stage = canonical_nearby(lat, lon, "stage", 25) or _nearby(stage_cache, lat, lon, 25)
    rain = canonical_nearby(lat, lon, "rain", 25) or _nearby(rain_cache, lat, lon, 25)
    usable_stage = [row for row in stage if row.get("waterlevel_msl_m") is not None or row.get("waterlevel_station_m") is not None]
    measured_rain = [row for row in rain if row.get("rain_1h_mm") is not None or row.get("rain_24h_mm") is not None]

    # Rain gauges are catchment observations; they do not need river-reach connectivity.
    basin_rain = _same_catchment_stations(catchment, measured_rain)
    positive_rain = [row for row in basin_rain if (row.get("rain_1h_mm") or 0) > 0 or (row.get("rain_24h_mm") or 0) > 0]

    # Stage gauges need actual natural-river topology where possible.  Same-catchment alone
    # remains supporting context rather than a verified upstream/downstream relationship.
    topology_links = hydraulic_station_links(lat, lon, usable_stage)
    connected_stage = [row for row in topology_links if row.get("hydraulic_relation") in {
        "CONNECTED_SAME_REACH", "CONNECTED_UPSTREAM", "CONNECTED_DOWNSTREAM"
    }]
    basin_stage = _same_catchment_stations(catchment, usable_stage)

    river_warning, flash_warning, coastal_warning = _classify_warnings(warnings.get("items") or [])
    connected_overbank = [row for row in connected_stage
                          if str(row.get("diff_wl_bank_text") or "").strip().startswith("ล้นตลิ่ง")
                          or str(row.get("source_situation_level") or "") == "5"]

    if river_warning:
        river = _result(_warning_status(river_warning), ["SCOPED_OFFICIAL_WARNING"], river_warning)
    elif connected_overbank:
        river = _result(
            "PARTIAL",
            ["CONNECTED_STATION_PROVIDER_OVERBANK", "BANK_REFERENCE_STATION_SCOPED_NOT_LOCATION_DEPTH"],
            [{"source": "ThaiWater", "station_id": row.get("station_id"),
              "hydraulic_relation": row.get("hydraulic_relation"),
              "waterlevel_msl_m": row.get("waterlevel_msl_m"),
              "diff_wl_bank_m": row.get("diff_wl_bank_m"),
              "diff_wl_bank_text": row.get("diff_wl_bank_text"),
              "source_situation_level": row.get("source_situation_level"),
              "distance_km_approx": row.get("distance_km_approx")} for row in connected_overbank],
        )
    elif connected_stage:
        bank_verified_stage = [row for row in connected_stage
                               if row.get("bank_reference_quality") == "RUNTIME_CROSSCHECKED"
                               and row.get("bank_level_msl_m") is not None]
        bank_evidence = [{
            "source": "ThaiWater",
            "station_id": row.get("station_id"),
            "station_code": row.get("station_code"),
            "observed_at_source": row.get("observed_at_source"),
            "waterlevel_msl_m": row.get("waterlevel_msl_m"),
            "bank_distance_m": row.get("bank_distance_m"),
            "bank_relation_text": row.get("bank_relation_text"),
            "bank_level_msl_m": row.get("bank_level_msl_m"),
            "bank_reference_validation": row.get("bank_reference_validation"),
            "hydraulic_relation": row.get("hydraulic_relation"),
            "station_reach_id": row.get("station_reach_id"),
            "target_reach_id": row.get("target_reach_id"),
            "waterlevel_msl_m": row.get("waterlevel_msl_m"),
            "source_situation_level": row.get("source_situation_level"),
            "distance_km_approx": row.get("distance_km_approx"),
        } for row in (bank_verified_stage or connected_stage)]
        reasons = ["HYDROLOGICALLY_CONNECTED_STAGE"]
        reasons.append("SOURCE_REPORTED_BANK_REFERENCE" if bank_verified_stage else
                       "BANK_OR_THRESHOLD_NOT_VERIFIED")
        if bank_verified_stage:
            reasons.append("STATION_BANK_REFERENCE_NOT_SELECTED_LOCATION_THRESHOLD")
        river = _result(
            "PARTIAL",
            reasons,
            bank_evidence,
        )
    elif basin_stage:
        river = _result(
            "PARTIAL",
            ["SAME_CATCHMENT_STAGE", "HYDRAULIC_LINK_UNVERIFIED"],
            [{"source": "ThaiWater", "station_id": row.get("station_id"),
              "distance_km_approx": row.get("distance_km_approx")} for row in basin_stage],
        )
    else:
        river = _result(
            "NOT_READY",
            ["NO_CONNECTED_STAGE_OR_SCOPED_WARNING"],
            [{"source": "ThaiWater", "station_id": row.get("station_id"),
              "distance_km_approx": row.get("distance_km_approx"), "context_only": True} for row in usable_stage],
        )

    if flash_warning:
        flash = _result(_warning_status(flash_warning), ["SCOPED_OFFICIAL_WARNING"], flash_warning)
    elif positive_rain and catchment:
        flash = _result(
            "PARTIAL",
            ["CATCHMENT_RAIN_OBSERVED", "RAIN_TRIGGER_THRESHOLD_UNVERIFIED", "WETNESS_UNVERIFIED"],
            [{"source": "ThaiWater", "station_id": row.get("station_id"),
              "rain_1h_mm": row.get("rain_1h_mm"), "rain_24h_mm": row.get("rain_24h_mm")} for row in positive_rain],
        )
    else:
        flash = _result("NOT_READY", ["NO_SCOPED_WARNING_OR_VERIFIED_RAIN_TRIGGER"])

    local_rain = (
        _result(
            "PARTIAL",
            ["NEARBY_RAIN_STATION", "RAINFALL_IS_CONTEXT_NOT_FLOOD_THRESHOLD"],
            [{"source": "ThaiWater", "station_id": row.get("station_id"),
              "rain_1h_mm": row.get("rain_1h_mm"), "rain_24h_mm": row.get("rain_24h_mm")} for row in measured_rain],
        )
        if measured_rain else _result("NOT_READY", ["NO_NEARBY_RAIN_OBSERVATION"])
    )

    province = (admin or {}).get("prov_name_th")
    tide_health = cached_source_health("navy_tide")
    tide_ingested = _ingested_tide_available()
    if province not in _COASTAL_PROVINCES:
        coastal = _result("NOT_APPLICABLE", ["LOCATION_NOT_IN_COASTAL_PROVINCE"])
    elif coastal_warning:
        coastal = _result(_warning_status(coastal_warning), ["SCOPED_COASTAL_WARNING"], coastal_warning)
    elif tide_ingested:
        coastal = _result(
            "PARTIAL",
            ["INGESTED_TIDE_PREDICTION_AVAILABLE", "DOWNSTREAM_BOUNDARY_PROPAGATION_UNVERIFIED"],
            [{"source": "navy_tide", "state": tide_health.get("state"),
              "last_observation": tide_health.get("last_observation")}],
        )
    else:
        coastal = _result("NOT_READY", ["NO_INGESTED_COASTAL_BOUNDARY_OR_TIDE_PREDICTION"])

    processes = [row for row in (river, flash, coastal, local_rain) if row["status"] in ("READY", "PARTIAL")]
    compound = (
        _result("PARTIAL", ["MULTIPLE_PROCESS_EVIDENCE_ONLY", "COMPOUND_LINKAGE_NOT_CALIBRATED"])
        if len(processes) >= 2 else _result("NOT_READY", ["FEWER_THAN_TWO_SUPPORTED_PROCESSES"])
    )

    hazards = dict(zip(HAZARDS, (river, flash, local_rain, coastal, compound)))
    relevant = (river, flash, coastal, compound)
    overall = (
        "READY" if any(row["status"] == "READY" for row in relevant) else
        "PARTIAL" if any(row["status"] == "PARTIAL" for row in relevant) else
        "NOT_READY"
    )

    situation = _situation_status(warnings=warnings, stage=usable_stage, rain=measured_rain,
                                  catchment=catchment, admin=admin)
    mode = "HAZARD_EVIDENCE" if overall == "READY" else "EVIDENCE_ONLY" if situation["ready"] else "NO_EVIDENCE"

    limitations: list[str] = []
    if usable_stage and not connected_stage:
        limitations.append("STAGE_STATION_HYDRAULIC_LINK_NOT_VERIFIED")
    if connected_stage and not any(row.get("bank_reference_quality") == "RUNTIME_CROSSCHECKED"
                                   for row in connected_stage):
        limitations.append("CONNECTED_STAGE_DOES_NOT_IMPLY_FLOOD_WITHOUT_BANK_THRESHOLD")
    if any(row.get("bank_reference_quality") == "RUNTIME_CROSSCHECKED" for row in connected_stage):
        limitations.append("STATION_BANK_REFERENCE_NOT_TRANSFERRED_TO_SELECTED_LOCATION")
    if measured_rain:
        limitations.append("RAINFALL_CONTEXT_NOT_CALIBRATED_FLOOD_TRIGGER")
    if warnings.get("reason") == "WARNING_SOURCE_STALE":
        limitations.append("OFFICIAL_WARNING_SOURCE_STALE")

    return {
        "location": {"latitude": lat, "longitude": lon},
        "admin": admin or None,
        "overall": overall,
        "mode": mode,
        "situation": situation,
        "hazards": hazards,
        "official_warnings": warnings,
        "outputs": {
            "situation_report": situation["ready"],
            "hazard_assessment": overall == "READY",
            "flood_probability": False,
            "peak_height": False,
            "arrival_time": False,
            "point_depth": False,
        },
        "limitations": limitations,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
