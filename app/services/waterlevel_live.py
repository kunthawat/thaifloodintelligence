"""Public ThaiWater station snapshots. These observations do not imply flood risk."""

from __future__ import annotations

import json
import hashlib
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from app.settings import ROOT

URL = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load"
CACHE = ROOT / "data" / "static" / "live" / "thaiwater_waterlevel.json"
MAX_AGE_SECONDS = 600
_lock = threading.Lock()


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _name(value):
    if isinstance(value, dict):
        return value.get("th") or value.get("en") or ""
    return value or ""


def _normalize(payload: dict) -> list[dict]:
    section = payload.get("waterlevel_data") or {}
    if section.get("result") != "OK" or not isinstance(section.get("data"), list):
        raise ValueError("ThaiWater waterlevel_data schema is unavailable")
    records = []
    for row in section["data"]:
        station = row.get("station") or {}
        lat = _number(station.get("tele_station_lat"))
        lon = _number(station.get("tele_station_long"))
        if lat is None or lon is None or not 5 <= lat <= 22 or not 97 <= lon <= 106:
            continue
        geocode = row.get("geocode") or {}
        agency = row.get("agency") or {}
        records.append({
            "station_id": str(station.get("id")),
            "station_code": station.get("tele_station_oldcode"),
            "name": _name(station.get("tele_station_name")),
            "lat": lat, "lon": lon,
            "tambon": _name(geocode.get("tumbon_name")),
            "amphoe": _name(geocode.get("amphoe_name")),
            "province": _name(geocode.get("province_name")),
            "agency": _name(agency.get("agency_name")),
            "observed_at_source": row.get("waterlevel_datetime"),
            "waterlevel_msl_m": _number(row.get("waterlevel_msl")),
            "waterlevel_station_m": _number(row.get("waterlevel_m")),
            "source_situation_level": row.get("situation_level"),
        })
    if not records:
        raise ValueError("ThaiWater returned no geolocated station records")
    return records


def _read_cache() -> dict | None:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None


def snapshot() -> dict:
    with _lock:
        cached = _read_cache()
        age = time.time() - CACHE.stat().st_mtime if cached else float("inf")
        if cached and age < MAX_AGE_SECONDS:
            return {**cached, "stale": False}
        try:
            request = Request(URL, headers={"Accept": "application/json", "User-Agent": "ThailandFloodIntelligence/0.1"})
            with urlopen(request, timeout=12) as response:
                payload = json.load(response)
            records = _normalize(payload)
            raw_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            result = {"source": URL, "fetched_at": datetime.now(timezone.utc).isoformat(),
                      "last_success_at": datetime.now(timezone.utc).isoformat(),
                      "source_timezone": "UNVERIFIED", "stations": records,
                      "raw_hash": raw_hash, "parser_version": "thaiwater-waterlevel-v1",
                      "quality_state": "PARTIAL"}
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            temporary = CACHE.with_suffix(".tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, CACHE)
            return {**result, "stale": False}
        except Exception as exc:
            if cached:
                return {**cached, "stale": True, "refresh_error": type(exc).__name__}
            return {"source": URL, "fetched_at": None, "source_timezone": "UNVERIFIED",
                    "stations": [], "stale": True, "refresh_error": type(exc).__name__}


def gauge_features(west: float, south: float, east: float, north: float) -> dict:
    data = snapshot()
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [item["lon"], item["lat"]]},
                 "properties": {key: value for key, value in item.items() if key not in ("lat", "lon")}}
                for item in data["stations"] if west <= item["lon"] <= east and south <= item["lat"] <= north]
    return {"type": "FeatureCollection", "features": features, "source": data["source"],
            "fetched_at": data["fetched_at"], "stale": data["stale"],
            "source_timezone": data["source_timezone"], "refresh_error": data.get("refresh_error")}


def nearby_gauges(lat: float, lon: float, limit: int = 5) -> dict:
    data = snapshot()
    ranked = sorted(data["stations"], key=lambda item: ((item["lat"] - lat) * 111.0) ** 2 +
                    ((item["lon"] - lon) * 111.0 * math.cos(math.radians(lat))) ** 2)
    items = []
    for item in ranked[:limit]:
        distance = math.hypot((item["lat"] - lat) * 111.0,
                              (item["lon"] - lon) * 111.0 * math.cos(math.radians(lat)))
        items.append({**item, "distance_km_approx": round(distance, 1)})
    return {"location": {"latitude": lat, "longitude": lon}, "items": items, "station_count": len(data["stations"]),
            "source": data["source"], "fetched_at": data["fetched_at"], "stale": data["stale"],
            "source_timezone": data["source_timezone"], "refresh_error": data.get("refresh_error")}
