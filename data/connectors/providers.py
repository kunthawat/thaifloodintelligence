"""Live connectors built from the implementation data manifest.

Connectors keep source payloads and provenance, and mark fields unavailable for
physics unless their units, time, datum, and station identity are supported.
"""

from __future__ import annotations

import asyncio
import calendar
import csv
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from app.services.sources import SOURCES, SourceDefinition
from app.settings import data_path
from data.connectors.base import (
    BlockedConnector,
    CanonicalObservation,
    ConnectorBlocker,
    ConnectorNotConfigured,
    DiscoveryResult,
    RawRecord,
    SemanticValidation,
    SourceHealth,
    TimeWindow,
    absolute_resource,
    anchors,
    decode_json,
    fetch_https,
    fetch_https_prefix,
    parse_float,
)

_DEFINITIONS = {source.source_id: source for source in SOURCES}
_HII_MISSING = {"-999", "999999", "9999", "-", "", "null", "none"}


class ProviderConnector:
    def __init__(self, source_id: str):
        self.source_id = source_id
        self.definition: SourceDefinition = _DEFINITIONS[source_id]
        self.last_errors: list[str] = []

    def _not_configured(self, detail: str) -> ConnectorNotConfigured:
        return ConnectorNotConfigured(ConnectorBlocker(self.source_id, "NOT_CONFIGURED", detail))

    def _endpoint(self) -> str:
        if not self.definition.enabled():
            raise self._not_configured("connector disabled by configuration")
        if not self.definition.endpoint():
            raise self._not_configured("endpoint is not configured")
        if self.definition.auth_envs and not all(os.getenv(key) for key in self.definition.auth_envs):
            raise self._not_configured("credentials are not configured")
        return self.definition.endpoint() or ""

    async def healthcheck(self) -> dict[str, Any]:
        if not self.definition.enabled():
            return {"status": "NOT_CONFIGURED", "message": "disabled by default", "freshness": "UNKNOWN"}
        if self.definition.auth_envs and not all(os.getenv(key) for key in self.definition.auth_envs):
            return {"status": "NOT_CONFIGURED", "message": "required credentials are not configured", "freshness": "UNKNOWN"}
        try:
            if self.source_id == "hii_catalog":
                discovery = await self.discover()
                message = None
                if discovery.status == "VALID_ZERO":
                    message = "หน้า catalog เชื่อมต่อได้ แต่ไม่พบไฟล์คลังย้อนหลังที่ดาวน์โหลดได้; ระบบยังใช้สถานีระดับน้ำสดจาก ThaiWater"
                return {"status": discovery.status, "message": message, "freshness": "ARCHIVE", "details": discovery.details}
            if self.source_id == "hii_legacy_graph":
                return {"status": "NOT_CONFIGURED", "message": "requires a station ID validated against returned station code/name", "freshness": "UNKNOWN"}
            if self.source_id == "tmd_qpe_ascii":
                return await self._health_tmd_qpe()
            if self.source_id == "navy_tide":
                return await self._health_navy()
            if self.source_id == "dwr_ews_station":
                return await self._health_dwr_stations()
            if self.source_id == "gistda_flood":
                return await self._health_gistda()
            if self.source_id == "imerg":
                return await self._health_imerg()
            if self.source_id == "dwr_ews_warnings":
                response = await fetch_https_prefix(_dwr_report_url(self._endpoint()), timeout=12)
                if response.status != 200:
                    return {"status": "SOURCE_ERROR", "http_status": response.status,
                            "message": f"HTTP {response.status}", "freshness": "UNKNOWN"}
                records = _dwr_recent_warnings(response.text, self.source_id, response.url)
                return {"status": "VALID" if _dwr_schema_recognized(response.text) else "NOT_SUPPORTED",
                        "http_status": 200, "latency_ms": response.latency_ms,
                        "freshness": "FRESH" if any((datetime.now(timezone.utc) - datetime.fromisoformat(record.observed_at).astimezone(timezone.utc)).total_seconds() <= 7200 for record in records) else "STALE_CONTEXT_ONLY" if records else "UNKNOWN",
                        "last_observation": max((record.observed_at for record in records), default=None),
                        "details": {"parsed_recent_warning_count": len(records), "bounded_report_prefix_bytes": len(response.body),
                                    "warning_is_not_hq_forcing": True}}
            endpoint = self._health_endpoint()
            params: dict[str, str] | None = None
            if self.source_id in {"ldd_landuse_admin", "ldd_landuse_subbasin", "dpm_hydrology"}:
                params = {"f": "pjson"}
            if self.source_id == "ldd_soil_query":
                layer_url = self._endpoint().rsplit("/query", 1)[0]
                response = await fetch_https(layer_url, params={"f": "pjson"}, timeout=4)
                if response.status != 200:
                    return {"status": "SOURCE_ERROR", "http_status": response.status, "message": f"LDD ArcGIS layer returned HTTP {response.status}", "freshness": "STATIC"}
                body = decode_json(response)
                if isinstance(body, dict) and body.get("error"):
                    return {"status": "SOURCE_ERROR", "http_status": 200, "message": "LDD ArcGIS layer returned an error object", "freshness": "STATIC"}
                return {"status": "VALID", "http_status": 200, "message": "ArcGIS soil query layer is reachable; no location-specific query was made", "freshness": "STATIC", "details": {"point_query_available": True, "native_spatial_reference": _spatial_reference(body)}}
            if self.source_id == "hii_legacy_daily":
                params = None  # endpoint includes the current Thailand date
            response = await fetch_https(endpoint, params=params,
                                         timeout=10 if self.source_id == "thaiwater_rain_24h" else 4,
                                         max_bytes=16 * 1024 * 1024 if self.source_id == "thaiwater_rain_24h" else 2 * 1024 * 1024)
            if response.status != 200:
                return {"status": "SOURCE_ERROR", "http_status": response.status, "latency_ms": response.latency_ms, "message": f"HTTP {response.status}", "freshness": "UNKNOWN"}
            details: dict[str, Any] = {"content_type": response.content_type}
            last_observed = None
            if self.source_id == "hii_legacy_daily":
                records = _hii_html_records(response.text, self.source_id)
                details["parsed_record_count"] = len(records)
                if not records:
                    return {"status": "NOT_SUPPORTED", "http_status": response.status,
                            "latency_ms": response.latency_ms,
                            "message": "Daily page was reachable but no station observation rows were parsed",
                            "freshness": "UNKNOWN", "details": details}
            if self.source_id == "thaiwater_v3":
                from app.services.waterlevel_live import _normalize
                records = _normalize(decode_json(response))
                details["parsed_station_count"] = len(records)
                details["with_msl_count"] = sum(record["waterlevel_msl_m"] is not None for record in records)
                details["source_timezone"] = "UNVERIFIED"
                last_observed = max((record["observed_at_source"] for record in records if record["observed_at_source"]), default=None)
            if self.source_id == "thaiwater_rain_24h":
                from app.services.rainfall_live import normalize
                records = normalize(decode_json(response))
                details["parsed_station_count"] = len(records)
                details["with_rain_24h_count"] = sum(record["rain_24h_mm"] is not None for record in records)
                details["source_timezone"] = "UNVERIFIED"
                details["rainfall_usable"] = False
                last_observed = max((record["observed_at_source"] for record in records if record["observed_at_source"]), default=None)
            if self.source_id in {"dwr_ews_warnings", "hii_public_warning"}:
                schema_ok = _warning_schema_recognized(response.text)
                details.update({"warning_schema_recognized": schema_ok, "warning_is_not_hq_forcing": True})
                if not schema_ok:
                    return {"status": "NOT_SUPPORTED", "http_status": response.status, "latency_ms": response.latency_ms, "message": "page reachable; warning-list time/status columns were not recognized", "freshness": "UNKNOWN", "details": details}
            if self.source_id in {"rid_dam", "rid_reservoir"}:
                data = decode_json(response)
                records = _record_list(data)
                if not records:
                    return {"status": "SOURCE_ERROR", "http_status": response.status, "latency_ms": response.latency_ms, "message": "JSON response has no recognized reservoir record list", "freshness": "UNKNOWN"}
                details["record_count"] = len(records)
                last_observed = _most_recent_date(records)
            elif self.source_id.startswith("ldd_landuse_") or self.source_id == "dpm_hydrology":
                data = decode_json(response)
                if isinstance(data, dict) and data.get("error"):
                    return {"status": "SOURCE_ERROR", "http_status": response.status, "latency_ms": response.latency_ms, "message": "ArcGIS layer returned an error", "freshness": "UNKNOWN"}
                details["layer_name"] = data.get("name") if isinstance(data, dict) else None
                details["spatial_reference"] = _spatial_reference(data)
                if self.source_id == "dpm_hydrology":
                    layer_ids = sorted(int(item.get("id")) for item in (data.get("layers") or []) if item.get("id") is not None)
                    details["layer_ids"] = layer_ids
                    details["reference_layers_available"] = all(value in layer_ids for value in (4, 5, 6))
                    if not details["reference_layers_available"]:
                        return {"status": "NOT_SUPPORTED", "http_status": response.status, "latency_ms": response.latency_ms,
                                "message": "DPM hydrology service is reachable but required layers 4/5/6 are missing",
                                "freshness": "STATIC", "details": details}
            elif self.source_id == "tmd_radar_discovery":
                product = _find_tmd_qpe_href(response.url, response.text)
                details["qpe_ascii_href"] = product
                details["utc_timestamps"] = True
            elif self.source_id == "dwr_ews_station":
                details["station_code"] = "STN0029"
                details["station_identity_verified"] = _contains_station_code(response.text, "STN0029")
                details["stage_usable"] = False
                details["rainfall_usable"] = False
                if not details["station_identity_verified"]:
                    return {"status": "SOURCE_ERROR", "http_status": response.status, "latency_ms": response.latency_ms, "message": "response did not identify STN0029; no observations accepted", "freshness": "UNKNOWN"}
            return {"status": "VALID", "http_status": response.status, "latency_ms": response.latency_ms, "message": None, "freshness": "UNKNOWN", "last_observation": last_observed, "details": details}
        except ConnectorNotConfigured as exc:
            return {"status": "NOT_CONFIGURED", "message": exc.blocker.detail, "freshness": "UNKNOWN"}
        except Exception as exc:
            return {"status": "SOURCE_ERROR", "message": f"source check failed ({type(exc).__name__})", "freshness": "UNKNOWN"}

    def _health_endpoint(self) -> str:
        endpoint = self._endpoint()
        if self.source_id == "hii_legacy_daily":
            today = datetime.now(ZoneInfo("Asia/Bangkok")).date().isoformat()
            return endpoint.replace("{date}", quote(today))
        if self.source_id == "dwr_ews_station":
            return endpoint.replace("{station_code}", "STN0029")
        if self.source_id == "thaiwater_v3":
            path = os.getenv("THAIWATER_V3_WATERLEVEL_PATH", "/api/v1/thaiwater30/public/waterlevel_load")
            return endpoint.rstrip("/") + "/" + path.lstrip("/")
        if self.source_id == "thaiwater_rain_24h":
            return endpoint.rstrip("/") + "/api/v1/thaiwater30/public/rain_24h"
        return endpoint

    async def _health_tmd_qpe(self) -> dict[str, Any]:
        discovery_url = os.getenv("TMD_RADAR_DISCOVERY_URL", _DEFINITIONS["tmd_radar_discovery"].default_url or "")
        page = await fetch_https(discovery_url, timeout=4)
        if page.status != 200:
            return {"status": "SOURCE_ERROR", "http_status": page.status, "message": f"Radar discovery page returned HTTP {page.status}", "freshness": "UNKNOWN"}
        target = _find_tmd_qpe_href(page.url, page.text)
        if not target:
            return {"status": "SOURCE_ERROR", "http_status": 200, "message": "Nationwide QPE ASCII link was not found on current discovery page; rainfall fallback active", "freshness": "UNKNOWN"}
        response = await fetch_https(target, headers={"Range": "bytes=0-8191"}, timeout=5, max_bytes=2 * 1024 * 1024)
        if response.status == 404:
            return {"status": "SOURCE_ERROR", "http_status": 404, "message": "Current discovery target returned 404; rainfall fallback active", "freshness": "UNKNOWN", "details": {"target": target}}
        if response.status not in {200, 206}:
            return {"status": "SOURCE_ERROR", "http_status": response.status, "message": f"QPE target returned HTTP {response.status}; rainfall fallback active", "freshness": "UNKNOWN"}
        if not response.body.startswith(b"PK\x03\x04"):
            return {"status": "SOURCE_ERROR", "http_status": response.status, "message": "QPE target is not a ZIP payload; rainfall fallback active", "freshness": "UNKNOWN"}
        return {"status": "VALID", "http_status": response.status, "latency_ms": response.latency_ms, "message": "ZIP header reachable; full grid/header/units validation runs during ingest", "freshness": "UNKNOWN", "details": {"target": target, "payload_validation": "PENDING_INGEST", "semantics": "UNVERIFIED"}}

    async def _health_dwr_stations(self) -> dict[str, Any]:
        template = self._endpoint()
        candidates = [value.strip() for value in os.getenv("DWR_EWS_PROBE_STATIONS", "STN0029,STN0168").split(",") if value.strip()]
        attempts = []
        for code in candidates[:5]:
            try:
                response = await fetch_https(template.replace("{station_code}", quote(code, safe="")), timeout=5)
                matched = response.status == 200 and _contains_station_code(response.text, code)
                attempts.append({"station_code": code, "http_status": response.status, "identity_verified": matched})
                if matched:
                    return {"status": "VALID", "http_status": response.status, "latency_ms": response.latency_ms,
                            "message": "At least one DWR station page passed identity validation; numeric model semantics remain unverified",
                            "freshness": "UNKNOWN",
                            "details": {"probe_attempts": attempts, "stage_usable": False, "rainfall_usable": False}}
            except Exception as exc:
                attempts.append({"station_code": code, "error": type(exc).__name__})
        return {"status": "SOURCE_ERROR", "message": "No configured DWR probe station passed reachability and identity validation",
                "freshness": "UNKNOWN", "details": {"probe_attempts": attempts, "stage_usable": False, "rainfall_usable": False}}

    async def _health_navy(self) -> dict[str, Any]:
        response = await fetch_https(self._endpoint(), timeout=4)
        if response.status != 200:
            return {"status": "SOURCE_ERROR", "http_status": response.status, "message": f"Navy tide index returned HTTP {response.status}", "freshness": "UNKNOWN"}
        current_year = str(datetime.now(ZoneInfo("Asia/Bangkok")).year)
        candidates = _navy_year_links(response.url, response.text, current_year)
        return {"status": "VALID" if candidates else "SOURCE_ERROR", "http_status": response.status,
                "message": "Tide index/resources discovered; readiness requires successfully ingested prediction rows" if candidates else f"Current-year {current_year} tide table not found",
                "freshness": "UNKNOWN",
                "details": {"year": current_year, "msl_resources": len(candidates), "products_are_forecasts": True,
                            "index_only": True, "ingested_prediction_required_for_readiness": True}}

    async def _health_gistda(self) -> dict[str, Any]:
        base = self._endpoint().rstrip("/")
        key = os.getenv("GISTDA_API_KEY")
        if not base or not key:
            return {"status": "NOT_CONFIGURED", "message": "GISTDA_API_BASE/API key not configured", "freshness": "UNKNOWN"}
        header = os.getenv("GISTDA_AUTH_HEADER", "Authorization")
        scheme = os.getenv("GISTDA_AUTH_SCHEME", "Bearer")
        headers = {header: f"{scheme} {key}".strip()}
        response = await fetch_https(base + "/features/flood/1day", headers=headers, timeout=5)
        if response.status in {401, 403}:
            return {"status": "NOT_CONFIGURED", "http_status": response.status, "message": "GISTDA credentials were rejected", "freshness": "UNKNOWN"}
        if response.status != 200:
            return {"status": "SOURCE_ERROR", "http_status": response.status, "message": f"GISTDA returned HTTP {response.status}", "freshness": "UNKNOWN"}
        body = decode_json(response)
        return {"status": "VALID", "http_status": 200, "message": None, "freshness": "UNKNOWN", "details": {"feature_count": _feature_count(body), "empty_result_is_not_no_flood": True}}

    async def _health_imerg(self) -> dict[str, Any]:
        endpoint = self._endpoint()
        token = os.getenv("IMERG_TOKEN")
        username, password = os.getenv("IMERG_USERNAME"), os.getenv("IMERG_PASSWORD")
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            import base64
            headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        response = await fetch_https(endpoint, headers=headers, timeout=5)
        if response.status in {401, 403}:
            return {"status": "NOT_CONFIGURED", "http_status": response.status, "message": "IMERG credentials were rejected", "freshness": "UNKNOWN"}
        if response.status != 200:
            return {"status": "SOURCE_ERROR", "http_status": response.status, "message": f"IMERG directory returned HTTP {response.status}", "freshness": "UNKNOWN"}
        return {"status": "VALID", "http_status": 200, "message": "authenticated product directory reachable; rainfall data normalization remains disabled pending file schema and units verification", "freshness": "UNKNOWN", "details": {"rainfall_usable": False, "product": "IMERG Early", "semantics": "PARTIAL"}}

    async def discover(self) -> DiscoveryResult:
        endpoint = self._health_endpoint()
        response = await fetch_https(endpoint, timeout=5)
        if response.status != 200:
            return DiscoveryResult(self.source_id, "SOURCE_ERROR", endpoint, details={"http_status": response.status})
        if self.source_id == "hii_catalog":
            resources = _catalog_resources(response.url, response.text)
            # An empty archive listing is a successful catalog check with zero
            # downloadable files, not an unsupported connector or provider.
            status = "VALID" if resources else "VALID_ZERO"
            return DiscoveryResult(self.source_id, status, endpoint, tuple(resources),
                                   details={"http_status": response.status, "archive_count": len(resources),
                                            "archive_available": bool(resources),
                                            "reason": None if resources else "NO_HTTPS_ARCHIVE_RESOURCE"})
        resources: list[dict[str, str]] = []
        for anchor in anchors(response.text):
            if anchor["href"]:
                try:
                    href = absolute_resource(response.url, anchor["href"])
                except ValueError:
                    continue
                resources.append({"url": href, "label": anchor["text"], "title": anchor["title"], "alt": anchor["alt"]})
        return DiscoveryResult(self.source_id, "VALID", endpoint, tuple(resources), details={"http_status": response.status, "content_type": response.content_type})

    async def fetch(self, window: TimeWindow | None = None, **options: Any) -> list[RawRecord]:
        self._endpoint()
        sid = self.source_id
        if sid == "hii_catalog":
            if options.get("archive_url"):
                return await self.fetch_hii_archive(str(options["archive_url"]), options.get("station_code"))
            discovery = await self.discover()
            return [RawRecord(sid, item.get("url"), item) for item in discovery.resources]
        if sid == "hii_legacy_graph":
            return await self.fetch_hii_graph(
                str(options.get("provider_station_id", "")),
                str(options.get("expected_station_code", "")),
                str(options.get("expected_station_name", "")),
            )
        if sid == "hii_legacy_daily":
            endpoint = self._endpoint()
            source_date = (window.end if window and window.end else datetime.now(ZoneInfo("Asia/Bangkok"))).strftime("%Y-%m-%d")
            response = await fetch_https(endpoint.replace("{date}", source_date), timeout=5)
            _require_ok(response)
            return _hii_html_records(response.text, sid)
        if sid == "hii_public_warning":
            response = await fetch_https(self._endpoint(), timeout=5)
            _require_ok(response)
            return _warning_records(response.text, sid, response.url)
        if sid == "dwr_ews_warnings":
            response = await fetch_https_prefix(_dwr_report_url(self._endpoint()), timeout=12)
            _require_ok(response)
            return _dwr_recent_warnings(response.text, sid, response.url)
        if sid == "dwr_ews_station":
            station_code = str(options.get("station_code", "STN0029"))
            return await self.fetch_dwr_station(station_code)
        if sid == "dwr_southwest":
            response = await fetch_https(self._endpoint(), timeout=5)
            _require_ok(response)
            return [RawRecord(sid, response.url, {"discovery_only": True, "content_type": response.content_type})]
        if sid == "tmd_radar_discovery":
            response = await fetch_https(self._endpoint(), timeout=5)
            _require_ok(response)
            target = _find_tmd_qpe_href(response.url, response.text)
            return [RawRecord(sid, response.url, {"qpe_ascii_href": target, "timestamps_timezone": "UTC"})]
        if sid == "tmd_qpe_ascii":
            payload = await self.download_tmd_qpe()
            return [RawRecord(sid, payload["url"], payload)]
        if sid in {"rid_dam", "rid_reservoir"}:
            return await self._fetch_rid(window)
        if sid == "navy_tide":
            return await self.fetch_navy_tide(str(options.get("station", "")), int(options.get("year", datetime.now(ZoneInfo("Asia/Bangkok")).year)))
        if sid == "gistda_flood":
            return await self.fetch_gistda(str(options.get("period", "1day")))
        if sid == "imerg":
            return await self.fetch_imerg()
        if sid.startswith("ldd_"):
            if sid == "ldd_soil_query":
                return [RawRecord(sid, None, await self.query_ldd_point(float(options["lon"]), float(options["lat"]))) ]
            return [RawRecord(sid, self._endpoint(), await self.fetch_ldd_layer())]
        if sid in {"thaiwater_v3", "thaiwater_rain_24h"}:
            response = await fetch_https(self._health_endpoint(), timeout=10,
                                         max_bytes=16 * 1024 * 1024 if sid == "thaiwater_rain_24h" else 2 * 1024 * 1024)
            _require_ok(response)
            body = decode_json(response)
            return [RawRecord(sid, None, {"payload": body, "semantics": "UNVERIFIED"})]
        raise self._not_configured("connector fetch is not implemented for this source")

    async def fetch_hii_archive(self, archive_url: str, station_code: str | None = None) -> list[RawRecord]:
        """Download an archive only after discovering its resource on data.go.th."""
        catalog = await fetch_https(self._endpoint(), timeout=6)
        _require_ok(catalog)
        allowed = {resource["url"] for resource in _catalog_resources(catalog.url, catalog.text)}
        if archive_url not in allowed:
            raise ValueError("archive URL was not discovered from the official water-level catalog")
        response = await fetch_https(archive_url, timeout=15, max_bytes=80 * 1024 * 1024)
        _require_ok(response)
        raw_dir = data_path("RAW_DATA_DIR", "data/raw") / "hii"
        raw_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".zip" if response.body.startswith(b"PK\x03\x04") else Path(response.url.split("?", 1)[0]).suffix or ".csv"
        fingerprint = hashlib.sha256(response.body).hexdigest()
        archived_path = raw_dir / f"{fingerprint[:16]}{suffix}"
        if not archived_path.exists():
            archived_path.write_bytes(response.body)
        csv_blobs: list[tuple[str, bytes]] = []
        if suffix.casefold() == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
                    if archive.testzip():
                        raise ValueError("HII archive ZIP CRC check failed")
                    csv_blobs = [(name, archive.read(name)) for name in archive.namelist() if name.casefold().endswith(".csv")]
            except zipfile.BadZipFile as exc:
                raise ValueError("HII archive ZIP is invalid") from exc
        else:
            csv_blobs = [(archived_path.name, response.body)]
        if not csv_blobs:
            raise ValueError("HII archive contains no CSV table")
        output: list[RawRecord] = []
        for name, blob in csv_blobs:
            output.extend(_hii_csv_records(blob, name, station_code, fingerprint))
        if not output:
            raise ValueError("HII archive schema/date/station columns were not recognized; no observations accepted")
        return output

    async def fetch_hii_graph(self, provider_station_id: str, expected_station_code: str, expected_station_name: str) -> list[RawRecord]:
        if not provider_station_id or not (expected_station_code or expected_station_name):
            raise self._not_configured("a candidate legacy ID and expected station identity are required")
        template = self._endpoint()
        url = template.replace("{legacy_id}", quote(provider_station_id, safe=""))
        response = await fetch_https(url, timeout=5)
        _require_ok(response)
        identity = _station_identity(response.text)
        if not _identity_matches(identity, expected_station_code, expected_station_name):
            raise ValueError("legacy provider ID identity mismatch; numeric ID was rejected and not persisted")
        return _hii_html_records(response.text, self.source_id, provider_station_id)

    async def fetch_dwr_station(self, station_code: str) -> list[RawRecord]:
        if not re.fullmatch(r"STN\d{4}", station_code):
            raise ValueError("DWR station code is not in the documented STN#### form")
        url = self._endpoint().replace("{station_code}", quote(station_code, safe=""))
        response = await fetch_https(url, timeout=5)
        _require_ok(response)
        if not _contains_station_code(response.text, station_code):
            raise ValueError("DWR station response identity did not match requested station code")
        return _hii_html_records(response.text, self.source_id, station_code)

    async def _fetch_rid(self, window: TimeWindow | None) -> list[RawRecord]:
        endpoint = self._endpoint()
        if window and window.end:
            date_value = window.end.date().isoformat()
            history_key = "RID_DAM_HISTORY_URL_TEMPLATE" if self.source_id == "rid_dam" else "RID_RESERVOIR_HISTORY_URL_TEMPLATE"
            template = os.getenv(history_key)
            if template:
                endpoint = template.replace("{date}", date_value)
            else:
                endpoint = endpoint.rstrip("/") + "/" + date_value
        response = await fetch_https(endpoint, timeout=5)
        _require_ok(response)
        data = decode_json(response)
        rows = _record_list(data)
        if not rows:
            raise ValueError("RID response did not contain a recognized record list")
        result: list[RawRecord] = []
        for index, row in enumerate(rows):
            record_id = row.get("id") or row.get("code") or f"{row.get('name', 'reservoir')}-{row.get('date', index)}"
            result.append(RawRecord(self.source_id, str(record_id), row, _source_date(row.get("date"))))
        return result

    async def fetch_navy_tide(self, station: str, year: int) -> list[RawRecord]:
        index = await fetch_https(self._endpoint(), timeout=5)
        _require_ok(index)
        resources = _navy_year_links(index.url, index.text, str(year), station)
        if not resources:
            raise ValueError(f"No current-year {year} MSL tide PDF was found for the selected station")
        results: list[RawRecord] = []
        self.last_errors = []
        semaphore = asyncio.Semaphore(3)

        async def download_one(resource: dict[str, str]) -> list[RawRecord]:
            async with semaphore:
                try:
                    response = await fetch_https(resource["url"], timeout=12, max_bytes=24 * 1024 * 1024)
                    _require_ok(response)
                    if not response.body.startswith(b"%PDF-"):
                        raise ValueError("resource was not a PDF")
                    points = _parse_tide_pdf(response.body, year, resource["station"])
                    if not points:
                        raise ValueError("PDF table rows were not recognized")
                    return [RawRecord(self.source_id, f"{resource['url']}:{point['predicted_at']}", {**point, "station": resource["station"], "datum": "MSL", "observation_type": "FORECAST", "source_url": resource["url"]}, point["predicted_at"]) for point in points]
                except Exception as exc:
                    self.last_errors.append(f"{resource['station']}: {type(exc).__name__}")
                    return []

        parts = await asyncio.gather(*(download_one(resource) for resource in resources))
        for part in parts:
            results.extend(part)
        if not results:
            raise ValueError("No Navy tide station PDF passed MSL, identity, time zone, and hourly table validation")
        return results

    async def download_tmd_qpe(self) -> dict[str, Any]:
        discovery_url = os.getenv("TMD_RADAR_DISCOVERY_URL", _DEFINITIONS["tmd_radar_discovery"].default_url or "")
        page = await fetch_https(discovery_url, timeout=5)
        _require_ok(page)
        url = _find_tmd_qpe_href(page.url, page.text)
        if not url:
            raise ValueError("Nationwide QPE ASCII link not present on current TMD discovery page")
        response = await fetch_https(url, timeout=15, max_bytes=80 * 1024 * 1024)
        _require_ok(response)
        header = _validate_qpe_zip(response.body)
        target_dir = data_path("RAW_DATA_DIR", "data/raw") / "tmd_qpe"
        target_dir.mkdir(parents=True, exist_ok=True)
        date_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = target_dir / f"qpe-{date_tag}.asc.zip"
        path.write_bytes(response.body)
        return {"url": url, "saved_path": str(path), "header": header, "payload_validated": True, "units": header.get("units"), "physics_eligible": False, "blocker": "QPE ASCII has no documented units in its grid header" if not header.get("units") else None, "timezone": "UTC"}

    async def fetch_gistda(self, period: str) -> list[RawRecord]:
        allowed = {"1day", "3days", "7days", "30days", "flood-freq"}
        if period not in allowed:
            raise ValueError(f"unsupported GISTDA flood period: {period}")
        base, key = self._endpoint().rstrip("/"), os.getenv("GISTDA_API_KEY")
        if not key:
            raise self._not_configured("GISTDA_API_KEY is not configured")
        header = os.getenv("GISTDA_AUTH_HEADER", "Authorization")
        scheme = os.getenv("GISTDA_AUTH_SCHEME", "Bearer")
        response = await fetch_https(base + f"/features/flood/{period}", headers={header: f"{scheme} {key}".strip()}, timeout=8, max_bytes=20 * 1024 * 1024)
        _require_ok(response)
        body = decode_json(response)
        features = body.get("features", []) if isinstance(body, dict) else []
        # Empty means no returned features in this response, not no inundation.
        return [RawRecord(self.source_id, str(item.get("id") or index), {"feature": item, "observation_type": "CONFIRMED_IMPACT", "period": period, "empty_result_is_not_no_flood": True}) for index, item in enumerate(features)]

    async def fetch_imerg(self) -> list[RawRecord]:
        token = os.getenv("IMERG_TOKEN")
        username, password = os.getenv("IMERG_USERNAME"), os.getenv("IMERG_PASSWORD")
        if not token and not (username and password):
            raise self._not_configured("IMERG_TOKEN or IMERG username/password are required")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if username and password:
            import base64
            basic = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {basic}"
        response = await fetch_https(self._endpoint(), headers=headers, timeout=8)
        _require_ok(response)
        return [RawRecord(self.source_id, response.url, {"directory_listing": response.text, "semantics": "UNVERIFIED", "product": "IMERG Early", "physics_eligible": False})]

    async def fetch_ldd_layer(self) -> dict[str, Any]:
        response = await fetch_https(self._endpoint(), params={"f": "pjson"}, timeout=5)
        _require_ok(response)
        payload = decode_json(response)
        return {"metadata": payload, "native_spatial_reference": _spatial_reference(payload), "source_crs": "EPSG:3857"}

    async def query_ldd_point(self, lon: float, lat: float) -> dict[str, Any]:
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("point coordinates must be WGS84 lon/lat")
        response = await fetch_https(self._endpoint(), params={
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }, timeout=8, max_bytes=8 * 1024 * 1024)
        _require_ok(response)
        payload = decode_json(response)
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("LDD ArcGIS point query returned an error")
        features = payload.get("features") or []
        return {"features": features, "count": len(features), "empty_result_is_not_zero_runoff": True, "requested_crs": "EPSG:4326", "source_crs": _spatial_reference(payload) or "service-native"}

    def normalize(self, raw: RawRecord) -> list[CanonicalObservation]:
        if raw.source_id != self.source_id:
            raise ValueError("raw record source does not match connector")
        if self.source_id in {"rid_dam", "rid_reservoir"}:
            return _normalize_rid(raw)
        if self.source_id in {"hii_catalog", "hii_legacy_daily", "hii_legacy_graph", "dwr_ews_station"}:
            return _normalize_stage(raw, self.definition)
        if self.source_id in {"dwr_ews_warnings", "hii_public_warning"}:
            return [CanonicalObservation("warning", str(raw.record_id or "unknown"), "OFFICIAL_WARNING", None, None, None, raw.observed_at, self.source_id, raw.record_id, "NOT_SUPPORTED", "OFFICIAL_WARNING", "UNVERIFIED", raw.payload, False, ("warning_is_not_H_OR_Q_forcing",))]
        if self.source_id == "navy_tide":
            return _normalize_tide(raw)
        if self.source_id == "gistda_flood":
            return [CanonicalObservation("flood_extent", str(raw.record_id or "unknown"), "CONFIRMED_IMPACT", None, None, None, raw.observed_at, self.source_id, raw.record_id, "ESTIMATED", "CONFIRMED_IMPACT", "PARTIAL", raw.payload, False, ("empty_results_do_not_prove_no_flood",))]
        return [CanonicalObservation("source_record", str(raw.record_id or "unknown"), "UNMAPPED", None, None, None, raw.observed_at, self.source_id, raw.record_id, "NOT_SUPPORTED", "OBSERVED", "UNVERIFIED", raw.payload, False, ("provider_schema_or_semantics_not_verified",))]

    def validate_semantics(self) -> SemanticValidation:
        if self.source_id == "rid_dam" or self.source_id == "rid_reservoir":
            return SemanticValidation("PARTIAL", ("capacity", "storage", "active_storage", "dead_storage", "volume", "percent_storage"), ("inflow", "outflow", "exact_observation_time"), ("RID inflow/outflow units are undocumented; never use them in physical mass balance",))
        if self.source_id.startswith("hii_"):
            return SemanticValidation("PARTIAL", ("water_level when explicit m MSL header and station identity match",), ("unknown archive schema", "unmatched station IDs", "legacy undocumented fields"), ("archive parser switches by observation date; unrecognized layouts stay unavailable",))
        if self.source_id == "navy_tide":
            return SemanticValidation("PARTIAL", ("year and MSL edition when explicitly selected",), ("PDF layouts that fail strict row parsing",), ("tide predictions are FORECAST, not observed sea level",))
        return SemanticValidation(self.definition.semantics_status, (), ("unverified fields are excluded from physical equations",), ("semantics validation is source and payload specific",))


def _health_result(source_id: str, data: dict[str, Any]) -> SourceHealth:
    return SourceHealth(source_id, str(data.get("status", "SOURCE_ERROR")), datetime.now(timezone.utc).isoformat(), data.get("http_status"), data.get("latency_ms"), data.get("last_observation"), data.get("message"), data.get("details") or {})


from data.connectors.static import StaticHydroConnector

CONNECTORS: dict[str, Any] = {definition.source_id: ProviderConnector(definition.source_id) for definition in SOURCES}
for _static_id in ("hydrosheds", "hydrobasins", "hydrorivers"):
    CONNECTORS[_static_id] = StaticHydroConnector(_static_id)
GLOBAL_PRECIP = BlockedConnector("global_precip", "Global precipitation fallback", "No additional global provider is specified; IMERG remains the configured cross-border fallback candidate")


def _require_ok(response: Any) -> None:
    if response.status != 200:
        raise RuntimeError(f"HTTP_{response.status}")


def _record_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items", "dam", "reservoir", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                for nested_key in ("data", "items", "results"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return [row for row in nested if isinstance(row, dict)]
    return []


def _most_recent_date(records: list[dict[str, Any]]) -> str | None:
    dates = [str(row.get("date")) for row in records if row.get("date")]
    return max(dates) if dates else None


def _source_date(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
        return parsed.astimezone(ZoneInfo("Asia/Bangkok")).isoformat()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if parsed.year > 2400:
                parsed = parsed.replace(year=parsed.year - 543)
            return parsed.replace(tzinfo=ZoneInfo("Asia/Bangkok")).isoformat()
        except ValueError:
            continue
    return None


class _TableParser:
    def __init__(self) -> None:
        from html.parser import HTMLParser

        class Parser(HTMLParser):
            def __init__(inner) -> None:
                super().__init__(convert_charrefs=True)
                inner.rows: list[list[str]] = []
                inner.row: list[str] | None = None
                inner.cell: list[str] | None = None
            def handle_starttag(inner, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                if tag == "tr": inner.row = []
                elif tag in {"td", "th"} and inner.row is not None: inner.cell = []
            def handle_data(inner, data: str) -> None:
                if inner.cell is not None: inner.cell.append(data.strip())
            def handle_endtag(inner, tag: str) -> None:
                if tag in {"td", "th"} and inner.row is not None and inner.cell is not None:
                    inner.row.append(" ".join(value for value in inner.cell if value)); inner.cell = None
                elif tag == "tr" and inner.row is not None:
                    if inner.row: inner.rows.append(inner.row)
                    inner.row = None
        self._parser = Parser()

    def rows(self, html: str) -> list[list[str]]:
        self._parser.feed(html)
        return self._parser.rows


def _hii_html_records(html: str, source_id: str, station_id: str | None = None) -> list[RawRecord]:
    rows = _TableParser().rows(html)
    records: list[RawRecord] = []
    header: list[str] | None = None
    for row_number, row in enumerate(rows):
        lowered = [item.casefold() for item in row]
        if any(any(term in cell for term in ("water level", "water_level", "ระดับน้ำ", "station code", "วันที่", "date")) for cell in lowered):
            header = row
            continue
        if not header or len(row) != len(header):
            continue
        payload = {header[index]: row[index] for index in range(len(header))}
        if station_id:
            payload["requested_station_id"] = station_id
        records.append(RawRecord(source_id, f"{station_id or 'row'}-{row_number}", payload, _extract_timestamp(payload)))
    return records


def _catalog_resources(base: str, html: str) -> list[dict[str, str]]:
    resources = []
    for item in anchors(html):
        if item["href"]:
            try:
                from data.connectors.base import absolute_resource
                url = absolute_resource(base, item["href"])
                if url.lower().split("?", 1)[0].endswith((".csv", ".zip")):
                    resources.append({"url": url, "label": item["text"]})
            except ValueError:
                continue
    return resources


def _hii_csv_records(blob: bytes, filename: str, station_code: str | None, checksum: str) -> list[RawRecord]:
    text = None
    for encoding in ("utf-8-sig", "cp874", "tis-620"):
        try:
            text = blob.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"HII CSV is not UTF-8/Thai legacy encoding: {filename}")
    rows = csv.DictReader(io.StringIO(text))
    if not rows.fieldnames:
        return []
    header_map = {str(field).strip().casefold(): field for field in rows.fieldnames}
    station_key = next((header_map[key] for key in header_map if key in {"station_code", "station code", "station_id", "station id", "รหัสสถานี", "รหัสสถานีโทรมาตร"}), None)
    value_key = next((header_map[key] for key in header_map if key in {"water_level", "water level", "ระดับน้ำ", "ระดับน้ํา", "wl"}), None)
    time_key = next((header_map[key] for key in header_map if key in {"datetime", "date_time", "date time", "observed_at", "timestamp", "วันที่เวลา", "วัน-เวลา", "date"}), None)
    unit_key = next((header_map[key] for key in header_map if key in {"unit", "water_level_unit", "หน่วย"}), None)
    datum_key = next((header_map[key] for key in header_map if key in {"datum", "reference_datum", "ระดับอ้างอิง"}), None)
    if not (station_key and value_key and time_key):
        return []
    output: list[RawRecord] = []
    for index, row in enumerate(rows):
        code = str(row.get(station_key) or "").strip()
        if station_code and code.casefold() != station_code.casefold():
            continue
        payload: dict[str, Any] = {
            "station_code": code,
            "water_level": row.get(value_key),
            "observed_at_raw": row.get(time_key),
            "unit": (row.get(unit_key) or "m") if unit_key else "m",
            "datum": (row.get(datum_key) or "MSL") if datum_key else "MSL",
            "unit_datum_source": "HII official water-level catalog" if not unit_key or not datum_key else "archive row",
            "parser_version": _hii_schema_version(row.get(time_key)),
            "archive_filename": filename,
            "archive_sha256": checksum,
        }
        observed = _parse_hii_time(payload["observed_at_raw"])
        output.append(RawRecord("hii_catalog", f"{filename}:{index}", payload, observed))
    return output


def _archive_date(filename: str, text: str) -> date:
    for value in (filename, text[:2000]):
        match = re.search(r"(?:19|20)\d{2}[-_/]?(?:0[1-9]|1[0-2])[-_/]?(?:0[1-9]|[12]\d|3[01])", value)
        if match:
            digits = re.sub(r"\D", "", match.group(0))
            try:
                return datetime.strptime(digits, "%Y%m%d").date()
            except ValueError:
                pass
    return date(2026, 2, 1)


def _parse_hii_time(value: Any) -> str | None:
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year > 2400:
                dt = dt.replace(year=dt.year - 543)
            return dt.replace(tzinfo=ZoneInfo("Asia/Bangkok")).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _hii_schema_version(value: Any) -> str:
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year > 2400:
                dt = dt.replace(year=dt.year - 543)
            return "thaiwater.standard" if dt.date() >= date(2026, 2, 1) else "legacy.csv"
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(ZoneInfo("Asia/Bangkok"))
        return "thaiwater.standard" if dt.date() >= date(2026, 2, 1) else "legacy.csv"
    except ValueError:
        return "UNRECOGNIZED_DATE_SCHEMA_BLOCKED"


def _dwr_report_url(url: str) -> str:
    return url if "on_yr=" in url else url + ("&" if "?" in url else "?") + \
        "on_basin=&on_dept=&on_prov=&on_status=&on_yr="


def _dwr_schema_recognized(html: str) -> bool:
    rows = _TableParser().rows(html)
    return bool(rows and all(any(token in cell for cell in rows[0])
                             for token in ("วันที่", "รายละเอียด", "ประเภทการเตือน")))


def _dwr_recent_warnings(html: str, source_id: str, url: str) -> list[RawRecord]:
    """Read recent rows from DWR's newest-first report, never the historical tail."""
    rows = _TableParser().rows(html)
    if not rows or "วันที่" not in " ".join(rows[0]):
        return []
    now = datetime.now(timezone.utc)
    result: list[RawRecord] = []
    for row in rows[1:]:
        if len(row) < 4:
            continue
        try:
            observed = datetime.strptime(row[1].strip(), "%d/%m/%y %H:%M").replace(
                tzinfo=ZoneInfo("Asia/Bangkok"))
        except ValueError:
            continue
        age_hours = (now - observed.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours < -1:
            continue
        if age_hours > 72:
            break
        description = row[2].strip()
        if not description.startswith("แจ้ง"):
            continue
        digest = hashlib.sha256("|".join(row[1:4]).encode("utf-8")).hexdigest()[:24]
        result.append(RawRecord(source_id, "dwr-" + digest,
                                {"row": row, "source_url": url,
                                 "observation_type": "OFFICIAL_WARNING", "forcing_eligible": False,
                                 "warning_basis": row[3].strip()},
                                observed.isoformat()))
    return result


def _warning_records(html: str, source_id: str, url: str) -> list[RawRecord]:
    rows = _warning_rows(html)
    result: list[RawRecord] = []
    header: list[str] | None = None
    for i, row in enumerate(rows):
        lowered = [cell.casefold() for cell in row]
        if any(any(word in cell for word in ("วันที่", "เวลา", "date", "time", "warning", "เตือนภัย", "สถานะ")) for cell in lowered):
            header = row
            continue
        if not header or len(row) != len(header):
            continue
        payload = {header[index]: row[index] for index in range(len(header))}
        joined = " | ".join(row)
        observed_at = _extract_timestamp(payload)
        is_warning = any(term in joined.casefold() for term in ("เตือนภัย", "warning", "แจ้งเตือน", "ระดับเฝ้าระวัง"))
        if is_warning and observed_at:
            result.append(RawRecord(source_id, f"{source_id}-{i}", {"row": row, "source_url": url, "observation_type": "OFFICIAL_WARNING", "forcing_eligible": False}, observed_at))
    return result


def _warning_rows(text: str) -> list[list[str]]:
    """Dispatch warning-list payloads across HTML tables, JSON records, and CSV."""
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith(("{", "[")):
        try:
            payload = json.loads(stripped)
            values: Any = payload
            if isinstance(payload, dict):
                values = next((payload[key] for key in ("warnings", "data", "items", "results", "records")
                               if isinstance(payload.get(key), list)), [])
            if isinstance(values, list) and values and all(isinstance(item, dict) for item in values):
                fields = list(dict.fromkeys(key for item in values for key in item))
                return [fields] + [[str(item.get(key, "")) for key in fields] for item in values]
        except (ValueError, TypeError):
            pass
    if "<" not in stripped and "\n" in stripped:
        try:
            parsed = [[str(cell).strip() for cell in row] for row in csv.reader(io.StringIO(stripped))]
            if parsed and any(any(term in cell.casefold() for term in ("date", "time", "วันที่", "เวลา", "warning", "เตือน"))
                              for cell in parsed[0]):
                return parsed
        except csv.Error:
            pass
    return _TableParser().rows(text)


def _warning_schema_recognized(html: str) -> bool:
    rows = _warning_rows(html)
    for row in rows:
        values = " ".join(row).casefold()
        has_time = any(term in values for term in ("วันที่", "เวลา", "date", "time", "issued"))
        has_status = any(term in values for term in ("warning", "เตือนภัย", "แจ้งเตือน", "สถานะ", "ระดับเฝ้าระวัง"))
        if has_time and has_status:
            return True
    return False


def _extract_timestamp(payload: dict[str, Any]) -> str | None:
    for key, value in payload.items():
        if not any(term in str(key).casefold() for term in ("date", "time", "เวลา", "วัน")):
            continue
        raw = str(value).strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    if dt.year > 2400:
                        dt = dt.replace(year=dt.year - 543)
                    dt = dt.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
                    break
                except ValueError:
                    dt = None
            if dt is None:
                continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
        return dt.astimezone(timezone.utc).isoformat()
    return None


def _normalize_stage(raw: RawRecord, source: SourceDefinition) -> list[CanonicalObservation]:
    payload = raw.payload
    lowered = {str(key).strip().casefold(): value for key, value in payload.items()}
    value_key = next((key for key in lowered if key in {"water_level", "water level", "ระดับน้ำ", "ระดับน้ํา", "h", "wl"}), None)
    if value_key is None:
        return []
    raw_value = str(lowered[value_key]).strip()
    station_code = next((str(value).strip() for key, value in payload.items() if any(term in str(key).casefold() for term in ("station code", "station_code", "รหัสสถานี", "station id"))), "")
    station_name = next((str(value).strip() for key, value in payload.items() if any(term in str(key).casefold() for term in ("station name", "station_name", "สถานี"))), "")
    unit_raw = next((str(value) for key, value in payload.items() if "unit" in str(key).casefold() or "หน่วย" in str(key)), "")
    datum_raw = next((str(value) for key, value in payload.items() if "datum" in str(key).casefold() or "อ้างอิง" in str(key)), "")
    missing = raw_value.casefold() in _HII_MISSING
    numeric = None if missing else parse_float(raw_value)
    explicit_m = (unit_raw.casefold() in {"m", "meter", "metre", "meters", "metres", "m msl"}
                  or "เมตร" in unit_raw or "ม.รทก." in unit_raw)
    explicit_msl = "msl" in (unit_raw + " " + datum_raw).casefold() or "ม.รทก." in (unit_raw + " " + datum_raw)
    unit = "m" if explicit_m else unit_raw or None
    datum = "MSL" if explicit_msl else datum_raw or None
    verified = (source.source_id == "hii_catalog" and explicit_m and explicit_msl
                and bool(station_code or station_name) and numeric is not None
                and raw.observed_at is not None
                and payload.get("parser_version") != "UNRECOGNIZED_DATE_SCHEMA_BLOCKED")
    reasons: list[str] = []
    state = "MISSING" if missing or numeric is None else "VALID_ZERO" if verified and numeric == 0 else "VALID" if verified else "SUSPECT"
    if not explicit_m: reasons.append("UNIT_NOT_EXPLICITLY_METRES")
    if not explicit_msl: reasons.append("DATUM_NOT_EXPLICITLY_MSL")
    if not (station_code or station_name): reasons.append("STATION_IDENTITY_MISSING")
    if raw.observed_at is None: reasons.append("OBSERVATION_TIMESTAMP_NOT_PARSED")
    if source.source_id != "hii_catalog": reasons.append("LEGACY_SOURCE_SEMANTICS_UNVERIFIED")
    historical_archive = "archive_filename" in payload
    if historical_archive: reasons.append("HISTORICAL_ARCHIVE_NOT_LIVE_CURRENT")
    return [CanonicalObservation("station", station_code or station_name or "unmatched", "WATER_LEVEL", numeric if not missing else None, unit, datum, raw.observed_at, raw.source_id, raw.record_id, state, "OBSERVED", "VERIFIED" if verified else "UNVERIFIED", payload, verified and not historical_archive, tuple(reasons))]


def _normalize_rid(raw: RawRecord) -> list[CanonicalObservation]:
    row = raw.payload
    identity = str(row.get("id") or row.get("code") or row.get("name") or "unknown")
    observed_at = raw.observed_at
    date_field = str(row.get("date") or "")
    exact_time = bool(re.search(r"\b\d{1,2}:\d{2}\b", date_field))
    age_hours: float | None = None
    if observed_at:
        try:
            parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600
        except ValueError:
            pass
    outputs: list[CanonicalObservation] = []
    for field, variable, unit in (
        ("capacity", "RESERVOIR_CAPACITY_MCM", "million m3"),
        ("storage", "RESERVOIR_STORAGE_MCM", "million m3"),
        ("active_storage", "RESERVOIR_ACTIVE_STORAGE_MCM", "million m3"),
        ("dead_storage", "RESERVOIR_DEAD_STORAGE_MCM", "million m3"),
        ("volume", "RESERVOIR_VOLUME_MCM", "million m3"),
        ("percent_storage", "RESERVOIR_PERCENT_STORAGE", "%"),
    ):
        if field not in row:
            continue
        value = parse_float(row.get(field))
        if value is None:
            state, eligible = "MISSING", False
        elif age_hours is not None and age_hours > 48:
            state, eligible = "STALE", False
        elif not exact_time or age_hours is None or age_hours < -0.1 or age_hours > 6:
            state, eligible = "SUSPECT", False
        else:
            state, eligible = "VALID", True
        reasons = () if eligible else ("date_only_source_timestamp_not_precise_enough_for_current_forcing",)
        outputs.append(CanonicalObservation("reservoir", identity, variable, value, unit if value is not None else None, None, observed_at, raw.source_id, raw.record_id, state, "OBSERVED", "VERIFIED", row, eligible, reasons))
    for field in ("inflow", "outflow"):
        if field not in row:
            continue
        outputs.append(CanonicalObservation("reservoir", identity, f"RID_RAW_{field.upper()}", parse_float(row.get(field)), None, None, observed_at, raw.source_id, raw.record_id, "SUSPECT", "OBSERVED", "UNVERIFIED", row, False, ("RID_FLOW_UNIT_UNDOCUMENTED_PHYSICS_LOCKED",)))
    return outputs


def _normalize_tide(raw: RawRecord) -> list[CanonicalObservation]:
    value = parse_float(raw.payload.get("predicted_level_m"))
    return [CanonicalObservation("boundary", str(raw.payload.get("station", "unknown")), "PREDICTED_TIDE_LEVEL", value, "m" if value is not None else None, "MSL", raw.observed_at, raw.source_id, raw.record_id, "VALID" if value is not None else "MISSING", "FORECAST", "PARTIAL", raw.payload, False, ("forecast_not_observed_sea_level", "inland_use_requires_tidal_river_propagation"))]


def _normalize_qpe_grid(raw: RawRecord) -> dict[str, Any]:
    data = raw.payload
    # The ASCII raster normally has no unit declaration in the file header.
    # Keep the grid archived, but do not create rain forcing without a verified unit.
    return {"source_id": raw.source_id, "raw_payload": data, "observation_type": "OBSERVED", "quality_state": "NOT_SUPPORTED", "physics_eligible": False, "reason": "QPE_GRID_UNIT_NOT_VERIFIED"}


def _find_tmd_qpe_href(base: str, html: str) -> str | None:
    for item in anchors(html):
        label = " ".join((item["text"], item["alt"], item["title"])).casefold()
        if "nationwide" in label and "qpe" in label and ("ascii" in label or "ascii" in item["href"].casefold()):
            return absolute_resource(base, item["href"])
    return None


def _validate_qpe_zip(body: bytes) -> dict[str, Any]:
    if not body.startswith(b"PK\x03\x04"):
        raise ValueError("QPE response is not a ZIP archive")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"QPE ZIP CRC check failed for {bad}")
            names = [name for name in archive.namelist() if name.casefold().endswith((".asc", ".txt"))]
            if not names:
                raise ValueError("QPE ZIP contains no ASCII grid")
            with archive.open(names[0]) as stream:
                header_bytes = stream.read(8192)
            header_text = header_bytes.decode("ascii", errors="replace")
            header: dict[str, float | str] = {}
            for line in header_text.splitlines()[:12]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0].casefold() in {"ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"}:
                    parsed = parse_float(parts[1])
                    if parsed is not None:
                        header[parts[0].casefold()] = parsed
            required = {"ncols", "nrows", "cellsize", "nodata_value"}
            if not required.issubset(header):
                raise ValueError("ASCII grid header is incomplete")
            header.update({"member": names[0], "units": None, "units_status": "UNVERIFIED"})
            return header
    except zipfile.BadZipFile as exc:
        raise ValueError("QPE ZIP archive is invalid or truncated") from exc


def _contains_station_code(html: str, code: str) -> bool:
    return bool(re.search(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", re.sub(r"<[^>]*>", " ", html), re.I))


def _station_identity(html: str) -> dict[str, str]:
    text = re.sub(r"<[^>]*>", " ", html)
    text = " ".join(text.split())
    code_match = re.search(r"\b(?:station\s*(?:code|id)?|รหัสสถานี)\s*[:：]?\s*([A-Z0-9.]+)", text, re.I)
    name_match = re.search(r"\b(?:station\s*name|สถานี)\s*[:：]?\s*([^|,;]{2,80})", text, re.I)
    return {"code": code_match.group(1) if code_match else "", "name": name_match.group(1).strip() if name_match else ""}


def _identity_matches(identity: dict[str, str], code: str, name: str) -> bool:
    if code and identity.get("code", "").casefold() == code.casefold():
        return True
    return bool(name and identity.get("name", "").strip().casefold() == name.strip().casefold())


class _NavyTableParser:
    def __init__(self) -> None:
        from html.parser import HTMLParser

        class Parser(HTMLParser):
            def __init__(inner) -> None:
                super().__init__(convert_charrefs=True)
                inner.rows: list[list[dict[str, Any]]] = []
                inner.row: list[dict[str, Any]] | None = None
                inner.cell: dict[str, Any] | None = None
                inner.in_anchor = False

            def handle_starttag(inner, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                values = {key.lower(): value or "" for key, value in attrs}
                if tag == "tr": inner.row = []
                elif tag in {"td", "th"} and inner.row is not None: inner.cell = {"text": "", "links": []}
                elif tag == "a" and inner.cell is not None:
                    inner.cell["links"].append(values.get("href", "")); inner.in_anchor = True

            def handle_data(inner, data: str) -> None:
                if inner.cell is not None: inner.cell["text"] += data.strip() + " "

            def handle_endtag(inner, tag: str) -> None:
                if tag == "a": inner.in_anchor = False
                elif tag in {"td", "th"} and inner.row is not None and inner.cell is not None:
                    inner.cell["text"] = " ".join(inner.cell["text"].split())
                    inner.row.append(inner.cell); inner.cell = None
                elif tag == "tr" and inner.row is not None:
                    if inner.row: inner.rows.append(inner.row)
                    inner.row = None
        self.parser = Parser()

    def rows(self, html: str) -> list[list[dict[str, Any]]]:
        self.parser.feed(html)
        return self.parser.rows


def _navy_year_links(base: str, html: str, year: str, station: str | None = None) -> list[dict[str, str]]:
    page_text = re.sub(r"<[^>]*>", " ", html)
    buddhist_year = str(int(year) + 543)
    if year not in page_text and buddhist_year not in page_text:
        return []
    rows = _NavyTableParser().rows(html)
    msl_column: int | None = None
    for row in rows:
        for index, cell in enumerate(row):
            label = cell["text"].casefold()
            if "mean sea level" in label or re.search(r"\bmsl\b", label):
                msl_column = index
                break
        if msl_column is not None:
            break
    if msl_column is None:
        return []
    found: list[dict[str, str]] = []
    for row in rows:
        if not row or len(row) <= msl_column:
            continue
        station_name = row[0]["text"]
        if not station_name or not row[msl_column]["links"]:
            continue
        if station and station.casefold() not in station_name.casefold():
            continue
        for href in row[msl_column]["links"]:
            if not href:
                continue
            url = absolute_resource(base, href)
            if not url.casefold().endswith(".pdf") or year not in url:
                continue
            found.append({"url": url, "label": station_name, "station": station_name})
    return found


def _parse_tide_pdf(pdf_bytes: bytes, year: int, expected_station: str = "") -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader  # optional dependency, loaded only when tide ingestion runs
    except ImportError as exc:
        raise ConnectorNotConfigured(ConnectorBlocker("navy_tide", "PARSER_NOT_INSTALLED", "Install the optional pypdf dependency to extract tide prediction PDFs")) from exc
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    # The Navy index joins Thai and English station names with a comma, while
    # the PDF prints the localized names on separate lines with location labels.
    # Validate either complete name instead of requiring the combined index label.
    station_aliases = [part.strip() for part in re.split(r"[,;|/]", expected_station) if len(part.strip()) >= 3]
    if station_aliases and not any(alias.casefold() in text.casefold() for alias in station_aliases):
        raise ValueError("Navy PDF station name does not match the index row")
    if "mean sea level" not in text.casefold() and "ระดับทะเลปานกลาง" not in text:
        raise ValueError("Navy PDF does not confirm an MSL edition")
    result: list[dict[str, Any]] = []
    months = {name.casefold(): index for index, name in enumerate(calendar.month_name) if name}
    month = None
    row_pattern = re.compile(r"^\s*(\d{1,2})\s+((?:-?\d+(?:\.\d+)?\s+){23}-?\d+(?:\.\d+)?)\s*$")
    for line in text.splitlines():
        month_match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b", line, re.I)
        if month_match and int(month_match.group(2)) == year:
            month = months[month_match.group(1).casefold()]
            continue
        match = row_pattern.match(line)
        if not match or month is None:
            continue
        day = int(match.group(1))
        if day > calendar.monthrange(year, month)[1]:
            continue
        levels = [float(value) for value in match.group(2).split()]
        if len(levels) != 24:
            continue
        for hour, level in enumerate(levels):
            dt = datetime(year, month, day, hour, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
            result.append({"predicted_at": dt.isoformat(), "predicted_level_m": level})
    return result


def _feature_count(payload: Any) -> int | None:
    if isinstance(payload, dict) and isinstance(payload.get("features"), list):
        return len(payload["features"])
    return None


def _spatial_reference(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    reference = payload.get("spatialReference") or payload.get("extent", {}).get("spatialReference")
    if not isinstance(reference, dict):
        return None
    wkid = reference.get("latestWkid") or reference.get("wkid")
    return f"EPSG:{wkid}" if wkid else None
