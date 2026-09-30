"""Manifest-backed source catalog and cached, truthful source health."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.settings import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    provider: str
    dataset: str
    endpoint_type: str
    url_env: str
    default_url: str | None
    semantics_status: str = "UNVERIFIED"
    native_unit: str | None = None
    native_datum: str | None = None
    native_timezone: str | None = None
    aggregation_interval: str | None = None
    expected_update_pattern: str | None = None
    warn_after: str | None = None
    reject_after: str | None = None
    fallback_group: str | None = None
    license: str | None = None
    commercial_use_status: str = "REVIEW_REQUIRED"
    auth_envs: tuple[str, ...] = ()
    enable_env: str | None = None
    default_enabled: bool = True
    source_status: str = "DISCOVER_AT_RUNTIME"
    priority: int = 100

    def endpoint(self) -> str | None:
        return os.getenv(self.url_env) or self.default_url

    def enabled(self) -> bool:
        return os.getenv(self.enable_env, "true" if self.default_enabled else "false").lower() in {"1", "true", "yes", "on"} if self.enable_env else self.default_enabled

    def configured(self) -> bool:
        if not self.enabled():
            return False
        if self.source_id == "imerg":
            return bool(os.getenv("IMERG_TOKEN") or (os.getenv("IMERG_USERNAME") and os.getenv("IMERG_PASSWORD")))
        return all(bool(os.getenv(name)) for name in self.auth_envs)


SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition("hii_catalog", "Hydro-Informatics Institute", "Water-level catalog and historical archive discovery", "CATALOG", "HII_DATASET_CATALOG_URL", "https://data.go.th/th/dataset/water-level", "VERIFIED", "m", "MSL", "Asia/Bangkok", "10 minutes", "archive / batch", None, None, "stage", "CC BY-NC (catalog-reported)", "NON_COMMERCIAL_REPORTED", source_status="VERIFIED_PUBLIC", priority=10),
    SourceDefinition("hii_legacy_daily", "Hydro-Informatics Institute", "Legacy daily water-level report", "HTML", "HII_LEGACY_DAILY_URL_TEMPLATE", "https://tiwrm.hii.or.th/DATA/REPORT/php/show_itcwater.php?sdate={date}", "UNVERIFIED", native_timezone="Asia/Bangkok", expected_update_pattern="historical fallback / discovery", fallback_group="stage", enable_env="ENABLE_HII_LEGACY", source_status="DISCOVERED_UNSTABLE", priority=40),
    SourceDefinition("hii_legacy_graph", "Hydro-Informatics Institute", "Legacy per-station water-level graph", "HTML", "HII_LEGACY_GRAPH_URL_TEMPLATE", "https://tiwrm.hii.or.th/DATA/REPORT/php/itc_graph2.php?id1={legacy_id}%2C", "UNVERIFIED", "m", "MSL", "Asia/Bangkok", "10 minutes", "historical / current cross-check", "30 minutes", "2 hours", "stage", enable_env="ENABLE_HII_LEGACY", source_status="DISCOVERED_UNSTABLE", priority=30),
    SourceDefinition("hii_public_warning", "Hydro-Informatics Institute", "Public water-level warning page", "HTML", "HII_PUBLIC_WARNING_URL", "https://tiwrm.hii.or.th/thaiwater_l5/public/telemetering/wl/warning", "UNVERIFIED", native_timezone="Asia/Bangkok", expected_update_pattern="current cross-check", fallback_group="warning", enable_env="ENABLE_HII_LEGACY", source_status="DISCOVERED_UNSTABLE", priority=30),
    SourceDefinition("thaiwater_v3", "ThaiWater", "Public water-level station observations", "JSON", "THAIWATER_V3_BASE_URL", "https://api-v3.thaiwater.net", "PARTIAL", native_unit="m", native_datum="MSL (waterlevel_msl only)", auth_envs=(), enable_env="THAIWATER_V3_ENABLED", default_enabled=True, source_status="VERIFIED_PUBLIC", priority=20),
    SourceDefinition("thaiwater_rain_24h", "ThaiWater", "Public station rainfall, one and 24 hours", "JSON", "THAIWATER_V3_BASE_URL", "https://api-v3.thaiwater.net", "PARTIAL", native_unit="mm", auth_envs=(), enable_env="THAIWATER_V3_ENABLED", default_enabled=True, source_status="VERIFIED_PUBLIC", priority=20),
    SourceDefinition("dwr_ews_warnings", "Department of Water Resources", "EWS warning list", "HTML", "DWR_EWS_WARNING_URL", "https://ews.dwr.go.th/ews/warn_list.php?on_basin=&on_dept=&on_prov=&on_status=&on_yr=", "PARTIAL", native_timezone="Asia/Bangkok", expected_update_pattern="5-10 min", warn_after="30 minutes", reject_after="2 hours", fallback_group="warning", enable_env="ENABLE_DWR_EWS", source_status="DISCOVER_AT_RUNTIME", priority=10),
    SourceDefinition("dwr_ews_station", "Department of Water Resources", "EWS station time series", "HTML", "DWR_EWS_STATION_URL_TEMPLATE", "https://ews.dwr.go.th/ews/list_temp.php?link={station_code}", "UNVERIFIED", native_timezone="Asia/Bangkok", expected_update_pattern="5-15 min", warn_after="30 minutes", reject_after="2 hours", fallback_group="stage,rain", enable_env="ENABLE_DWR_EWS", source_status="DISCOVER_AT_RUNTIME", priority=15),
    SourceDefinition("dwr_southwest", "Department of Water Resources", "Southwest telemetry portal discovery", "HTML", "DWR_TELE_SOUTHWEST_URL", "https://tele-southwest.dwr.go.th/home/Index_HOME", "UNVERIFIED", native_timezone="Asia/Bangkok", enable_env="ENABLE_DWR_EWS", source_status="OPTIONAL", priority=90),
    SourceDefinition("tmd_radar_discovery", "Thai Meteorological Department", "Radar and nationwide QPE product discovery", "HTML", "TMD_RADAR_DISCOVERY_URL", "https://weather.tmd.go.th/chn.php", "PARTIAL", native_timezone="UTC", expected_update_pattern="5-10 min", warn_after="20 minutes", reject_after="60 minutes", fallback_group="rain", enable_env="ENABLE_TMD_RADAR", source_status="DISCOVER_AT_RUNTIME", priority=10),
    SourceDefinition("tmd_qpe_ascii", "Thai Meteorological Department", "Dynamically discovered nationwide QPE ASCII", "ZIP/ASCII", "TMD_QPE_ASCII_CANDIDATE", "https://weather.tmd.go.th/composite/compositeQPE_VTBB_latest.asc.zip", "UNVERIFIED", native_timezone="UTC", expected_update_pattern="5-10 min", warn_after="20 minutes", reject_after="60 minutes", fallback_group="rain", enable_env="ENABLE_TMD_RADAR", source_status="DISCOVERED_UNSTABLE", priority=10),
    SourceDefinition("rid_dam", "Royal Irrigation Department", "Large dam public state", "JSON", "RID_DAM_CURRENT_URL", "https://app.rid.go.th/reservoir/api/dam/public", "PARTIAL", expected_update_pattern="hourly", warn_after="6 hours", reject_after="48 hours", fallback_group="reservoir", license="Source terms require review", enable_env="ENABLE_RID_RESERVOIR", source_status="VERIFIED_RELATIVE_API", priority=15),
    SourceDefinition("rid_reservoir", "Royal Irrigation Department", "Medium reservoir public state", "JSON", "RID_RESERVOIR_CURRENT_URL", "https://app.rid.go.th/reservoir/api/reservoir/public", "PARTIAL", expected_update_pattern="hourly", warn_after="6 hours", reject_after="48 hours", fallback_group="reservoir", license="Source terms require review", enable_env="ENABLE_RID_RESERVOIR", source_status="VERIFIED_RELATIVE_API", priority=15),
    SourceDefinition("navy_tide", "Royal Thai Navy Hydrographic Department", "Current-year MSL tide predictions", "HTML/PDF", "NAVY_TIDE_INDEX_URL", "https://hydro.navy.mi.th/waterlaveltable", "PARTIAL", "m", "MSL when MSL edition is selected", "Asia/Bangkok", "hourly", "annual prediction table", None, "365 days", "coastal_boundary", enable_env="ENABLE_NAVY_TIDE", source_status="DISCOVER_AT_RUNTIME", priority=20),
    SourceDefinition("gistda_flood", "GISTDA", "Satellite-derived flood features and map products", "JSON/GeoJSON", "GISTDA_API_BASE", None, "PARTIAL", auth_envs=("GISTDA_API_KEY",), enable_env="GISTDA_ENABLED", default_enabled=False, source_status="KEY_REQUIRED", priority=20),
    SourceDefinition("imerg", "NASA GPM", "IMERG Early precipitation", "GIS/HTTP", "IMERG_GIS_ROOT", "https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/", "PARTIAL", native_timezone="UTC", expected_update_pattern="about 30 min product / about 4 h latency", warn_after="6 hours", reject_after="12 hours", fallback_group="cross_border_rain", auth_envs=("IMERG_USERNAME",), enable_env="IMERG_ENABLED", default_enabled=False, source_status="AUTH_REQUIRED", priority=60),
    SourceDefinition("hydrosheds", "HydroSHEDS", "Asia 3 arc-second conditioned DEM, flow direction, flow accumulation", "STATIC_GIS", "HYDROSHEDS_DOWNLOAD_PAGE", "https://www.hydrosheds.org/hydrosheds-core-downloads", "PARTIAL", priority=30, source_status="DISCOVER_AT_RUNTIME", enable_env="ENABLE_HYDROSHEDS"),
    SourceDefinition("hydrobasins", "HydroSHEDS", "Asia HydroBASINS levels 1-12", "STATIC_VECTOR", "HYDROBASINS_DOWNLOAD_PAGE", "https://www.hydrosheds.org/products/hydrobasins", "PARTIAL", priority=30, source_status="DISCOVER_AT_RUNTIME", enable_env="ENABLE_HYDROSHEDS"),
    SourceDefinition("hydrorivers", "HydroSHEDS", "Asia HydroRIVERS natural-river topology", "STATIC_VECTOR", "HYDRORIVERS_DOWNLOAD_PAGE", "https://www.hydrosheds.org/products/hydrorivers", "PARTIAL", priority=30, source_status="DISCOVER_AT_RUNTIME", enable_env="ENABLE_HYDROSHEDS"),
    SourceDefinition("dpm_hydrology", "Department of Disaster Prevention and Mitigation", "Main/secondary waterways and 22 major basins", "ARCGIS REST", "DPM_HYDROLOGY_BASE", "https://gis-portal.disaster.go.th/arcgis/rest/services/MapDX/DPM_TH_Hydrology/FeatureServer", "VERIFIED", native_timezone="Asia/Bangkok", expected_update_pattern="static/reference", priority=25, source_status="VERIFIED_PUBLIC", enable_env="ENABLE_DPM_HYDROLOGY"),
    SourceDefinition("ldd_landuse_admin", "Land Development Department", "Land use and soil query administrative layer", "ARCGIS REST", "LDD_LANDUSE_ADMIN_LAYER", "https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_QUERY_WM/MapServer/5", "PARTIAL", priority=40, source_status="VERIFIED_RELATIVE_API", enable_env="ENABLE_LDD"),
    SourceDefinition("ldd_landuse_subbasin", "Land Development Department", "Land use / soil subbasin layer", "ARCGIS REST", "LDD_LANDUSE_SUBBASIN_LAYER", "https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_QUERY_WM/MapServer/8", "PARTIAL", priority=40, source_status="VERIFIED_RELATIVE_API", enable_env="ENABLE_LDD"),
    SourceDefinition("ldd_soil_query", "Land Development Department", "Point soil and land-use feature query", "ARCGIS REST", "LDD_SOIL_FEATURE_QUERY", "https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_WM/FeatureServer/6/query", "PARTIAL", priority=40, source_status="VERIFIED_RELATIVE_API", enable_env="ENABLE_LDD"),
)

_HEALTH_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_TIME: dict[str, float] = {}
HEALTH_CACHE_SECONDS = 300


def get_source_registry() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for priority, source in enumerate(SOURCES):
        endpoint = source.endpoint()
        enabled = source.enabled()
        configured = source.configured()
        health = _HEALTH_CACHE.get(source.source_id)
        if not enabled:
            status, message = "NOT_CONFIGURED", "แหล่งข้อมูลนี้ปิดใช้งานตามค่าเริ่มต้น"
        elif source.auth_envs and not all(os.getenv(key) for key in source.auth_envs):
            status, message = "NOT_CONFIGURED", "ยังไม่ได้กำหนดข้อมูลยืนยันตัวตนที่จำเป็น"
        elif source.source_id == "gistda_flood" and not endpoint:
            status, message = "NOT_CONFIGURED", "GISTDA_API_BASE/API key not configured"
        elif health:
            status, message = health.get("status", "SOURCE_ERROR"), health.get("message")
        else:
            status, message = "NOT_CONFIGURED", "ยังไม่ได้ตรวจสอบการเชื่อมต่อแหล่งข้อมูล"
        rows.append({
            "source_id": source.source_id,
            "provider": source.provider,
            "dataset": source.dataset,
            "endpoint_type": source.endpoint_type,
            "base_url": endpoint,
            "native_unit": source.native_unit,
            "native_datum": source.native_datum,
            "native_timezone": source.native_timezone,
            "aggregation_interval": source.aggregation_interval,
            "semantics_status": source.semantics_status,
            "license": source.license,
            "commercial_use_status": source.commercial_use_status,
            "expected_update_pattern": source.expected_update_pattern,
            "freshness_warn_after": source.warn_after,
            "freshness_reject_after": source.reject_after,
            "priority": source.priority,
            "fallback_group": source.fallback_group,
            "auth_required": bool(source.auth_envs),
            "parser_version": "1",
            "enabled": enabled,
            "configured": configured,
            "source_status": source.source_status,
            "status": status,
            "message": message,
            "blocker": message,
            "last_check": health.get("last_check") if health else None,
            "last_success": health.get("last_success") if health else None,
            "last_observation": health.get("last_observation") if health else None,
        })
    return rows


def source_health() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in SOURCES:
        registry_row = next((item for item in _registry_lookup() if item["source_id"] == source.source_id), {})
        health = _HEALTH_CACHE.get(source.source_id, {})
        rows.append({
            "source_id": source.source_id,
            "state": registry_row.get("status", "NOT_CONFIGURED"),
            "checked_at": health.get("last_check"),
            "last_success_at": health.get("last_success"),
            "last_failure_at": health.get("last_failure"),
            "last_observation": health.get("last_observation"),
            "freshness": health.get("freshness", "UNKNOWN"),
            "semantics": source.semantics_status,
            "configured": source.configured(),
            "blocker": registry_row.get("message"),
            "details": health.get("details", {}),
        })
    return rows


def cached_source_health(source_id: str) -> dict[str, Any]:
    """Return one in-process source check without rebuilding the full registry."""
    health = _HEALTH_CACHE.get(source_id, {})
    return {
        "source_id": source_id,
        "state": health.get("status", "UNKNOWN"),
        "freshness": health.get("freshness", "UNKNOWN"),
        "last_observation": health.get("last_observation"),
        "checked_at": health.get("last_check"),
        "message": health.get("message"),
    }


def _registry_lookup() -> list[dict[str, Any]]:
    return get_source_registry()


def record_health_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist health observations when a migrated PostGIS database exists."""
    from app.settings import configured_database_url

    database_url = configured_database_url()
    if not database_url:
        return {"persisted": False, "reason": "DATABASE_URL/DATABASE_DSN not configured"}
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError:
        return {"persisted": False, "reason": "psycopg driver not installed"}
    saved = 0
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                for row in rows:
                    status = row.get("state", "SOURCE_ERROR")
                    if status not in {"VALID", "VALID_ZERO", "MISSING", "STALE", "SUSPECT", "NOT_SUPPORTED", "SOURCE_ERROR", "ESTIMATED", "NOT_CONFIGURED"}:
                        status = "SOURCE_ERROR"
                    details = row.get("details") or {}
                    cursor.execute(
                        """INSERT INTO source_health(source_id,checked_at,status,http_status,latency_ms,last_observed_at,
                             last_success_at,error_code,error_message,details)
                           VALUES (%s,COALESCE(%s::timestamptz,now()),%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (source_id,checked_at) DO NOTHING""",
                        (row["source_id"], row.get("checked_at"), status, row.get("http_status"), row.get("latency_ms"),
                         row.get("last_observation"), row.get("last_success_at"),
                         None if status == "VALID" else status, row.get("blocker"), Jsonb(details)),
                    )
                    saved += 1
        return {"persisted": True, "rows": saved}
    except Exception as exc:
        return {"persisted": False, "reason": type(exc).__name__}


async def refresh_source_health(force: bool = False) -> list[dict[str, Any]]:
    """Probe enabled public endpoints with strict time and response-size limits."""
    from data.connectors.providers import CONNECTORS

    now_mono = time.monotonic()
    pending = [
        source for source in SOURCES
        if source.enabled()
        and not (source.auth_envs and not all(os.getenv(key) for key in source.auth_envs))
        and (force or now_mono - _CACHE_TIME.get(source.source_id, 0) >= HEALTH_CACHE_SECONDS)
    ]

    async def check(source: SourceDefinition) -> None:
        connector = CONNECTORS.get(source.source_id)
        if connector is None:
            return
        try:
            result = await asyncio.wait_for(connector.healthcheck(),
                                            timeout=15 if source.source_id == "dwr_ews_warnings" else 6)
        except asyncio.TimeoutError:
            result = {"status": "SOURCE_ERROR", "message": "การตรวจสอบเกินเวลาที่กำหนด", "freshness": "UNKNOWN"}
        except Exception as exc:
            result = {"status": "SOURCE_ERROR", "message": f"ตรวจแหล่งข้อมูลไม่สำเร็จ ({type(exc).__name__})", "freshness": "UNKNOWN"}
        checked = datetime.now(timezone.utc).isoformat()
        previous = _HEALTH_CACHE.get(source.source_id, {})
        is_success = result.get("status") == "VALID"
        _HEALTH_CACHE[source.source_id] = {
            **result,
            "last_check": checked,
            "last_success": checked if is_success else previous.get("last_success"),
            "last_failure": checked if not is_success else previous.get("last_failure"),
        }
        _CACHE_TIME[source.source_id] = time.monotonic()

    await asyncio.gather(*(check(source) for source in pending))
    return source_health()
