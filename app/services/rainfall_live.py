"""Measured ThaiWater station rainfall, kept separate from flood predictions."""

from __future__ import annotations

import json
import hashlib
import math
import os
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from app.settings import ROOT
from app.services.waterlevel_live import _name, _number

URL = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/rain_24h"
CACHE = ROOT / "data" / "static" / "live" / "thaiwater_rain_24h.json"
MAX_AGE_SECONDS = 600
_lock = threading.Lock()


def normalize(payload: dict) -> list[dict]:
    if payload.get("result") != "OK" or not isinstance(payload.get("data"), list):
        raise ValueError("ThaiWater rain_24h schema is unavailable")
    records = []
    for row in payload["data"]:
        station = row.get("station") or {}
        lat = _number(station.get("tele_station_lat"))
        lon = _number(station.get("tele_station_long"))
        rain24 = _number(row.get("rain_24h"))
        rain1 = _number(row.get("rain_1h"))
        if lat is None or lon is None or not 5 <= lat <= 22 or not 97 <= lon <= 106:
            continue
        if rain24 is not None and rain24 < 0:
            rain24 = None
        if rain1 is not None and rain1 < 0:
            rain1 = None
        geocode = row.get("geocode") or {}
        records.append({
            "station_id": str(station.get("id")),
            "station_code": station.get("tele_station_oldcode"),
            "name": _name(station.get("tele_station_name")),
            "lat": lat, "lon": lon,
            "province": _name(geocode.get("province_name")),
            "agency": _name((row.get("agency") or {}).get("agency_name")),
            "observed_at_source": row.get("rainfall_datetime"),
            "rain_24h_mm": rain24,
            "rain_1h_mm": rain1,
        })
    if not records:
        raise ValueError("ThaiWater returned no geolocated rain stations")
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
            records = normalize(payload)
            raw_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            result = {"source": URL, "fetched_at": datetime.now(timezone.utc).isoformat(),
                      "last_success_at": datetime.now(timezone.utc).isoformat(),
                      "source_timezone": "UNVERIFIED", "stations": records,
                      "raw_hash": raw_hash, "parser_version": "thaiwater-rain-v1",
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


def rainfall_features(west: float, south: float, east: float, north: float) -> dict:
    data = snapshot()
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [item["lon"], item["lat"]]},
                 "properties": {key: value for key, value in item.items() if key not in ("lat", "lon")}}
                for item in data["stations"] if west <= item["lon"] <= east and south <= item["lat"] <= north]
    return {"type": "FeatureCollection", "features": features, "source": data["source"],
            "fetched_at": data["fetched_at"], "stale": data["stale"],
            "source_timezone": data["source_timezone"], "refresh_error": data.get("refresh_error")}


def nearby_rainfall(lat: float, lon: float, limit: int = 5) -> dict:
    data = snapshot()
    ranked = sorted(data["stations"], key=lambda item: ((item["lat"] - lat) * 111.0) ** 2 +
                    ((item["lon"] - lon) * 111.0 * math.cos(math.radians(lat))) ** 2)
    items = []
    for item in ranked[:limit]:
        distance = math.hypot((item["lat"] - lat) * 111.0,
                              (item["lon"] - lon) * 111.0 * math.cos(math.radians(lat)))
        items.append({**item, "distance_km_approx": round(distance, 1)})
    return {"location": {"latitude": lat, "longitude": lon}, "items": items,
            "station_count": len(data["stations"]), "source": data["source"],
            "fetched_at": data["fetched_at"], "stale": data["stale"],
            "source_timezone": data["source_timezone"], "refresh_error": data.get("refresh_error")}
