"""Conservative matching of Thai administrative warning text to DPM polygons."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.settings import configured_database_url

_LABELS = {
    "TAMBON": r"(?:ตำบล|ต\.|แขวง)",
    "AMPHOE": r"(?:อำเภอ|อ\.|เขต)",
    "PROVINCE": r"(?:จังหวัด|จ\.)",
}


def _names(text: str, level: str) -> list[str]:
    pattern = _LABELS[level] + r"\s*([ก-๙]+)"
    return list(dict.fromkeys(re.findall(pattern, text or "")))


def _connect():
    url = configured_database_url()
    if not url:
        raise RuntimeError("DATABASE_NOT_CONFIGURED")
    return psycopg.connect(url, connect_timeout=3, row_factory=dict_row)


def resolve_scope(cursor, text: str) -> dict[str, Any]:
    """Resolve only an explicit, uniquely identified administrative name.

    An ambiguous narrow name must not fall back to a wider province polygon.
    """
    names = {level: _names(text, level) for level in _LABELS}
    if any(len(values) > 1 for values in names.values()):
        return {"resolved": False, "reason": "MULTIPLE_ADMIN_NAMES"}
    for level, table, code, name in (
        ("TAMBON", "admin_tambon", "tam_code", "tam_name_th"),
        ("AMPHOE", "admin_amphoe", "amp_code", "amp_name_th"),
        ("PROVINCE", "admin_province", "prov_code", "prov_name_th"),
    ):
        if not names[level]:
            continue
        constraints = [f"{name}=%s"]
        params: list[str] = [names[level][0]]
        if names["AMPHOE"] and level == "TAMBON":
            constraints.append("amp_name_th=%s")
            params.append(names["AMPHOE"][0])
        if names["PROVINCE"] and level != "PROVINCE":
            constraints.append("prov_name_th=%s")
            params.append(names["PROVINCE"][0])
        cursor.execute(f"SELECT {code} AS code FROM {table} WHERE {' AND '.join(constraints)} LIMIT 2", params)
        rows = cursor.fetchall()
        if len(rows) != 1:
            return {"resolved": False, "reason": "ADMIN_NAME_AMBIGUOUS" if rows else "ADMIN_NAME_NOT_FOUND",
                    "admin_level": level, "name": names[level][0]}
        return {"resolved": True, "admin_level": level, "admin_code": rows[0][0],
                "scope_method": f"ADMIN_{level}_MATCH", "scope_confidence": 1.0,
                "scope_text_normalized": " ".join(filter(None, (names["TAMBON"] or [None])[0:1] +
                                                 (names["AMPHOE"] or [None])[0:1] +
                                                 (names["PROVINCE"] or [None])[0:1]))}
    return {"resolved": False, "reason": "NO_EXPLICIT_ADMIN_SCOPE"}


def scope_table(level: str) -> tuple[str, str] | None:
    return {"TAMBON": ("admin_tambon", "tam_code"),
            "AMPHOE": ("admin_amphoe", "amp_code"),
            "PROVINCE": ("admin_province", "prov_code")}.get(level)


def location_admin(lat: float, lon: float) -> dict[str, Any]:
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT p.prov_code,p.prov_name_th,a.amp_code,a.amp_name_th,
                                     t.tam_code,t.tam_name_th
                              FROM admin_province p
                              LEFT JOIN admin_amphoe a ON a.prov_code=p.prov_code
                                AND ST_Covers(a.geom,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                              LEFT JOIN admin_tambon t ON t.amp_code=a.amp_code
                                AND ST_Covers(t.geom,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                              WHERE ST_Covers(p.geom,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                              LIMIT 1""", (lon, lat, lon, lat, lon, lat))
            row = cursor.fetchone()
            return dict(row) if row else {}
    except (psycopg.Error, RuntimeError):
        return {}


def location_boundary(lat: float, lon: float) -> dict[str, Any]:
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT tam_code,tam_name_th,amp_name_th,prov_name_th,
                                     ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom,0.0001))::json AS geometry
                              FROM admin_tambon
                              WHERE ST_Covers(geom,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                              LIMIT 1""", (lon, lat))
            row = cursor.fetchone()
    except (psycopg.Error, RuntimeError):
        row = None
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": row["geometry"],
         "properties": {key: row[key] for key in ("tam_code", "tam_name_th", "amp_name_th", "prov_name_th")}}
    ] if row else [], "source": "DPM administrative boundaries"}


def scoped_warnings(lat: float, lon: float) -> dict[str, Any]:
    """Read stored warnings; unresolved scopes never count as covering a point."""
    try:
        from app.services.sources import cached_source_health
        dwr_health = cached_source_health("dwr_ews_warnings")
    except Exception:
        dwr_health = {}
    source = {
        "source_id": "dwr_ews_warnings",
        "state": dwr_health.get("state", "UNKNOWN"),
        "freshness": dwr_health.get("freshness", "UNKNOWN"),
        "last_observation": dwr_health.get("last_observation"),
        "checked_at": dwr_health.get("checked_at"),
    }
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT warning_id::text,source_id,issued_at,valid_to,severity,
                                     hazard_type::text,title,message,scope_method,scope_confidence,
                                     admin_level,admin_code,raw_payload->>'warning_basis' AS warning_basis
                              FROM official_warnings
                              WHERE issued_at >= now()-interval '2 hours'
                                AND (valid_to IS NULL OR valid_to >= now())
                                AND geom IS NOT NULL
                                AND ST_Covers(geom,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                              ORDER BY issued_at DESC LIMIT 30""", (lon, lat))
            items = [dict(row) for row in cursor.fetchall()]
            cursor.execute("""SELECT count(*) AS total,
                                     count(*) FILTER (WHERE geom IS NULL) AS unresolved
                              FROM official_warnings
                              WHERE issued_at >= now()-interval '2 hours'
                                AND (valid_to IS NULL OR valid_to >= now())""")
            counts = cursor.fetchone()
            cursor.execute("""SELECT source_id,issued_at,title,message,scope_method
                              FROM official_warnings
                              WHERE issued_at < now()-interval '2 hours'
                                AND issued_at >= now()-interval '72 hours'
                                AND geom IS NOT NULL
                                AND ST_Covers(geom,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                              ORDER BY issued_at DESC LIMIT 3""", (lon, lat))
            history = [dict(row) for row in cursor.fetchall()]
    except (psycopg.Error, RuntimeError):
        return {"available": False, "checked": False, "items": [],
                "source": source, "reason": "WARNING_DATABASE_UNAVAILABLE"}
    for item in items:
        for key in ("issued_at", "valid_to"):
            if isinstance(item.get(key), datetime):
                item[key] = item[key].astimezone(timezone.utc).isoformat()
    for item in history:
        item["issued_at"] = item["issued_at"].astimezone(timezone.utc).isoformat()
    source_valid = source["state"] in ("VALID", "VALID_ZERO")
    source_fresh = source["freshness"] == "FRESH"
    # Unresolved warnings elsewhere in Thailand are diagnostics only; they must not
    # make the warning source unavailable for this point.
    reason = ("WARNING_SOURCE_UNAVAILABLE" if not source_valid else
              "WARNING_SOURCE_STALE" if not source_fresh else
              "NO_CURRENT_WARNINGS" if not items else None)
    return {"available": bool(source_valid and source_fresh),
            "checked": True, "source": source, "items": items,
            "reason": reason,
            "active_record_count": counts["total"], "unresolved_record_count": counts["unresolved"],
            "historical_context": history, "historical_context_is_current": False}
