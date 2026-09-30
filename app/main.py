"""HTTP API and static application entry point."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models.forecast import build_forecast
from app.services.database import database_status
from app.services.geography import location_context as spatial_context, river_route, network_features, station_record
from app.services.places import search_places
from app.services.waterlevel_live import gauge_features, nearby_gauges
from app.services.rainfall_live import rainfall_features, nearby_rainfall
from app.services.sources import get_source_registry, record_health_results, refresh_source_health, source_health
from app.services.admin_scope import location_admin, location_boundary, scoped_warnings
from app.services.readiness import location_readiness
from app.services.warning_refresh import background_refresh

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

app = FastAPI(
    title="Thailand Flood Intelligence",
    description=(
        "Nationwide flood intelligence API. Forecast values remain unavailable "
        "until verified observations, models, and source semantics are configured."
    ),
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
)

app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.on_event("startup")
async def start_warning_refresh() -> None:
    app.state.warning_refresh_task = asyncio.create_task(background_refresh())


@app.on_event("shutdown")
async def stop_warning_refresh() -> None:
    app.state.warning_refresh_task.cancel()


def _coordinates(lat: float, lon: float) -> dict[str, float]:
    if not isfinite(lat) or not isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise HTTPException(status_code=422, detail="Coordinates must use valid WGS84 latitude and longitude.")
    return {"latitude": lat, "longitude": lon}


def _unavailable(reason: str, detail: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "detail": detail}


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "thailand-flood-intelligence",
        "database": database_status(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/places/search")
def places_search(q: str = Query(..., min_length=1), limit: int = Query(default=12, ge=1, le=50)) -> dict[str, Any]:
    return search_places(q, limit)


@app.get("/v1/layers/gauges")
def layer_gauges(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    return gauge_features(west, south, east, north)


@app.get("/v1/layers/rain")
def layer_rain(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    return rainfall_features(west, south, east, north)


@app.get("/v1/location/nearby-gauges")
def location_nearby_gauges(lat: float = Query(..., ge=-90, le=90),
                           lon: float = Query(..., ge=-180, le=180)) -> dict[str, Any]:
    return nearby_gauges(lat, lon)


@app.get("/v1/location/nearby-rain")
def location_nearby_rain(lat: float = Query(..., ge=-90, le=90),
                         lon: float = Query(..., ge=-180, le=180)) -> dict[str, Any]:
    return nearby_rainfall(lat, lon)


@app.get("/v1/location/context")
def location_context(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    coordinates = _coordinates(lat, lon)
    context = spatial_context(lat, lon)
    admin = location_admin(lat, lon)
    return {
        "location": coordinates,
        "place_name": admin,
        "within_thailand": bool(admin),
        "catchment": context["catchment"],
        "nearest_reach": context["nearest_reach"],
        "nearest_reference_waterway": context.get("nearest_reference_waterway"),
        "downstream_boundary": None,
        "network_confidence": context["network_confidence"],
        "availability": context["availability"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/location/risk")
def location_risk(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    coordinates = _coordinates(lat, lon)
    forecast = build_forecast(coordinates)
    readiness = location_readiness(lat, lon, spatial_context(lat, lon).get("catchment"))
    warnings = readiness["official_warnings"]
    return {
        "location": coordinates,
        "risk_level": "UNKNOWN",
        "overall_probability": None,
        "dominant_hazard": None,
        "hazards": {
            name: {"value": None, "eligible": False, "reason": "INSUFFICIENT_VALID_OBSERVATIONS"}
            for name in ("RIVER_OVERFLOW", "FLASH_FLOOD", "LOCAL_RAIN", "COASTAL_TIDAL", "COMPOUND")
        },
        "occurrence": forecast["occurrence"],
        "confidence": forecast["confidence"],
        "risk_drivers": [],
        "risk_reducers": [],
        "official_warning": warnings,
        "readiness": readiness,
        "data_state": readiness["overall"],
        "generated_at": forecast["generated_at"],
    }


@app.get("/v1/location/readiness")
def readiness_by_location(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    _coordinates(lat, lon)
    return location_readiness(lat, lon, spatial_context(lat, lon).get("catchment"))


@app.get("/v1/location/situation")
def location_situation(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    _coordinates(lat, lon)
    readiness = location_readiness(lat, lon, spatial_context(lat, lon).get("catchment"))
    return {
        "location": readiness["location"],
        "admin": readiness.get("admin"),
        "situation": readiness.get("situation"),
        "mode": readiness.get("mode"),
        "hazards": readiness.get("hazards"),
        "limitations": readiness.get("limitations", []),
        "official_warnings": readiness.get("official_warnings"),
        "generated_at": readiness.get("generated_at"),
    }


@app.get("/v1/location/admin-boundary")
def admin_boundary(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    _coordinates(lat, lon)
    return location_boundary(lat, lon)


@app.get("/v1/location/forecast")
def location_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    return build_forecast(_coordinates(lat, lon))


@app.get("/v1/location/forecast/curve")
def location_forecast_curve(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    hazard: str | None = None,
) -> dict[str, Any]:
    coordinates = _coordinates(lat, lon)
    return {
        "location": coordinates,
        "hazard": hazard,
        "recommended_timeline": [],
        "members": [],
        "available": False,
        "reason": "NO_ELIGIBLE_FORECAST",
        "detail": "ยังไม่มีข้อมูลและแบบจำลองที่ผ่านเกณฑ์สำหรับสร้างเส้นพยากรณ์",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/location/explanation")
def location_explanation(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    coordinates = _coordinates(lat, lon)
    context = spatial_context(lat, lon)
    uncertainties = [
        {"code": "INSUFFICIENT_VALID_OBSERVATIONS", "message": "ข้อมูลฝนและระดับน้ำปัจจุบันยังไม่ครบพอสำหรับประเมินความเสี่ยง"},
        {"code": "NO_ELIGIBLE_FORECAST", "message": "ยังไม่มีแบบจำลองที่ผ่านเกณฑ์สำหรับพยากรณ์เวลาและระดับน้ำ"},
    ]
    if not context["availability"]["available"]:
        uncertainties.append({"code": context["availability"]["reason"], "message": "ไม่พบขอบเขตลุ่มน้ำหรือลำน้ำที่ยืนยันแล้วสำหรับจุดนี้"})
    return {
        "location": coordinates,
        "risk_drivers": [],
        "risk_reducers": [],
        "evidence": {"catchment": context["catchment"], "nearest_reach": context["nearest_reach"],
                     "nearest_reference_waterway": context.get("nearest_reference_waterway")},
        "uncertainties": uncertainties,
        "availability": "INSUFFICIENT_DATA",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/network/upstream")
def network_upstream(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict[str, Any]:
    return {"location": _coordinates(lat, lon), **river_route(lat, lon, "upstream")}


@app.get("/v1/network/downstream")
def network_downstream(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict[str, Any]:
    return {"location": _coordinates(lat, lon), **river_route(lat, lon, "downstream"),
            "constraints": [], "constraints_available": False}


@app.get("/v1/network/source-to-outlet")
def network_source_to_outlet(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    location = _coordinates(lat, lon)
    upstream = river_route(lat, lon, "upstream", limit=60)
    downstream = river_route(lat, lon, "downstream", limit=120)
    features = []
    seen = set()
    for group, route in (("upstream", upstream), ("downstream", downstream)):
        for feature in (route.get("route_geojson") or {}).get("features", []):
            key = feature.get("id") or (feature.get("properties") or {}).get("reach_id")
            if key in seen:
                continue
            seen.add(key)
            copied = {**feature, "properties": {**(feature.get("properties") or {}), "route_group": group}}
            features.append(copied)
    return {
        "location": location,
        "available": bool(features),
        "reason": None if features else "NO_VERIFIED_ROUTE",
        "upstream": {key: upstream.get(key) for key in ("available", "reach_count", "total_length_m", "truncated")},
        "downstream": {key: downstream.get(key) for key in ("available", "reach_count", "total_length_m", "truncated", "terminal")},
        "terminal": downstream.get("terminal"),
        "route_geojson": {"type": "FeatureCollection", "features": features},
        "detail": "Natural-river topology from HydroRIVERS NEXT_DOWN; DPM waterways remain reference-only until directional topology is verified.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/network/waves")
def network_waves(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict[str, Any]:
    return {
        "location": _coordinates(lat, lon),
        "events": [],
        "available": False,
        "reason": "EVENT_DATA_UNAVAILABLE",
        "detail": "รายการว่างนี้หมายถึงยังเข้าถึงข้อมูลเหตุการณ์ไม่ได้ ไม่ได้ยืนยันว่าไม่มีคลื่นน้ำ",
    }


@app.get("/v1/events/{event_id}")
def event_details(event_id: str) -> dict[str, Any]:
    raise HTTPException(status_code=404, detail={"code": "EVENT_NOT_FOUND", "event_id": event_id})


@app.get("/v1/stations/{station_id}")
def station_details(station_id: str) -> dict[str, Any]:
    try:
        station = station_record(station_id)
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE"}) from None
    if station is None:
        raise HTTPException(status_code=404, detail={"code": "STATION_NOT_FOUND", "station_id": station_id})
    return station


@app.get("/v1/official-warnings")
async def official_warnings(
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
) -> dict[str, Any]:
    if (lat is None) != (lon is None):
        raise HTTPException(status_code=422, detail="Provide both lat and lon, or neither.")
    location = _coordinates(lat, lon) if lat is not None and lon is not None else None
    if location is None:
        return {"location": None, "items": [], "available": False,
                "reason": "LOCATION_REQUIRED_FOR_SCOPED_WARNINGS"}
    return {"location": location, **scoped_warnings(lat, lon)}


@app.get("/v1/data-quality")
async def data_quality(refresh: bool = Query(default=False)) -> dict[str, Any]:
    health_rows = await refresh_source_health(force=refresh)
    health_persistence = record_health_results(health_rows)
    registry = get_source_registry()
    health_by_source = {item["source_id"]: item for item in health_rows}
    required_warning = False
    measured_rain_available = (
        (item := health_by_source.get("thaiwater_rain_24h", {})).get("state") == "VALID"
        and item.get("details", {}).get("parsed_station_count", 0) > 0
    )
    required_rain = any(
        (item := health_by_source.get(source_id, {})).get("state") == "VALID"
        and item.get("details", {}).get("rainfall_usable") is True
        for source_id in ("tmd_qpe_ascii", "dwr_ews_station", "imerg")
    )
    db = database_status()
    required_warning = db.get("scoped_current_warning_count", 0) > 0
    gis_ready = bool(
        db.get("basin_count", 0) > 0
        and db.get("network_edge_count", 0) > 0
        and db.get("terrain_product_count", 0) >= 3
    )
    required_stage = any(
        (item := health_by_source.get(source_id, {})).get("state") == "VALID"
        and item.get("details", {}).get("stage_usable") is True
        for source_id in ("hii_legacy_daily", "hii_legacy_graph", "dwr_ews_station")
    )
    stage_observations_available = (
        (item := health_by_source.get("thaiwater_v3", {})).get("state") == "VALID"
        and item.get("details", {}).get("parsed_station_count", 0) > 0
    )
    any_evidence_path = bool(required_warning or measured_rain_available or stage_observations_available or
                             required_rain or required_stage)
    global_hazard_status = "PARTIAL" if gis_ready and any_evidence_path else "NOT_READY"
    situation_report_ready = bool(gis_ready and (any_evidence_path or db.get("admin_tambon_count", 0) > 0))
    return {
        "database": db,
        "source_health": health_rows or source_health(),
        "source_registry": registry,
        "source_health_persistence": health_persistence,
        "readiness": {
            "DATA_PLATFORM_READY": db.get("state") == "READY" and db.get("migrations_ready", False),
            "MAP_READY": gis_ready,
            "SITUATION_REPORT_READY": situation_report_ready,
            "HAZARD_ONLY_READY": global_hazard_status in {"READY", "PARTIAL"},
            "GLOBAL_HAZARD_STATUS": global_hazard_status,
            "QUANT_FORECAST_PARTIAL": False,
            "QUANT_FORECAST_READY": False,
            "POINT_DEPTH_READY": False,
            "conditions": {
                "official_warning_pathway": required_warning,
                "rain_station_observations_available": measured_rain_available,
                "stage_station_observations_available": stage_observations_available,
                "rainfall_pathway": required_rain,
                "stage_or_hazard_pathway": required_stage or required_warning,
                "gis_imported": gis_ready,
                "postgis_connected": db.get("state") == "READY",
                "migrations_ready": db.get("migrations_ready", False),
            },
            "blockers": [name for name, ready in (
                ("POSTGIS_MIGRATIONS_NOT_READY", db.get("migrations_ready", False)),
                ("GIS_PRODUCTS_NOT_IMPORTED", gis_ready),
            ) if not ready],
            "degraded_capabilities": [name for name, ready in (
                ("NO_CURRENT_SCOPED_OFFICIAL_WARNING", required_warning),
                ("NO_VERIFIED_NUMERIC_RAINFALL_MODEL_INPUT", required_rain),
                ("NO_STAGE_OR_WARNING_PATHWAY", required_stage or required_warning or stage_observations_available),
            ) if not ready],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/layers/{layer_name}")
def map_layer(layer_name: str, west: float | None = None, south: float | None = None,
              east: float | None = None, north: float | None = None) -> dict[str, Any]:
    supported = {
        "risk", "flow", "rain", "official-warnings", "flood-extent", "gauges",
        "reservoirs", "controls", "terrain", "hand", "historical-flood", "network-confidence",
    }
    if layer_name not in supported:
        raise HTTPException(status_code=404, detail={"code": "LAYER_NOT_SUPPORTED", "layer": layer_name})
    if layer_name in {"flow", "network-confidence"}:
        if None in (west, south, east, north) or not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise HTTPException(status_code=422, detail="Provide a valid west,south,east,north viewport.")
        try:
            rows = network_features(west, south, east, north)
        except Exception:
            rows = []
        return {"layer": layer_name, "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": row["id"], "geometry": row["geometry"],
                              "properties": {"network_confidence": row.get("network_confidence"),
                                             "reach_id": row.get("reach_id"),
                                             "name_th": row.get("name_th"),
                                             "source": row.get("source"),
                                             "waterway_class": row.get("waterway_class"),
                                             "topology_role": row.get("topology_role")}}
                             for row in rows],
                "available": bool(rows), "reason": None if rows else "NO_FEATURES_IN_VIEWPORT",
                "detail": "Detailed DPM waterways provide map reference geometry; HydroRIVERS provides regional NEXT_DOWN topology."}
    return {
        "layer": layer_name,
        "type": "FeatureCollection",
        "features": [],
        "available": False,
        "reason": "LAYER_SOURCE_NOT_CONFIGURED",
        "detail": "ยังไม่มีข้อมูลชั้นแผนที่จากแหล่งที่เชื่อมต่อและตรวจสอบแล้ว",
    }
