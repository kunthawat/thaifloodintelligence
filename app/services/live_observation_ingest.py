"""Persist ThaiWater live station snapshots into the canonical observation store.

The live map cache is a transport cache, not the system of record.  This module
bridges the already-normalized ThaiWater snapshots into ``observations`` and
``observation_quality`` without pretending that calibration/model eligibility
has been established.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.settings import configured_database_url

BANGKOK = ZoneInfo("Asia/Bangkok")
_STAGE_MAX_AGE_HOURS = 2.0
_RAIN_MAX_AGE_HOURS = 2.0


def _observed_at(value: str | None) -> tuple[datetime | None, list[str]]:
    if not value:
        return None, ["OBSERVATION_TIMESTAMP_MISSING"]
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None, ["OBSERVATION_TIMESTAMP_PARSE_FAILED"]
    reasons: list[str] = []
    if parsed.tzinfo is None:
        # ThaiWater currently emits local-looking station timestamps without an
        # explicit offset.  Use Thailand local time for freshness/evidence, but
        # retain the assumption in provenance.  This does NOT make the source
        # fully model/physics eligible.
        parsed = parsed.replace(tzinfo=BANGKOK)
        reasons.append("SOURCE_TIMEZONE_ASSUMED_ASIA_BANGKOK")
    return parsed.astimezone(timezone.utc), reasons


def _age_hours(value: datetime | None) -> float | None:
    if value is None:
        return None
    return (datetime.now(timezone.utc) - value).total_seconds() / 3600.0


def _state(value: float | None, observed_at: datetime | None, max_age_hours: float) -> tuple[str, bool]:
    if value is None:
        return "MISSING", False
    age = _age_hours(observed_at)
    if age is None or age < -1.0:
        return "SUSPECT", False
    if age > max_age_hours:
        return "STALE", False
    return ("VALID_ZERO" if value == 0 else "VALID"), True


def _jsonb(cursor: Any, value: Any) -> Any:
    # Import lazily so importing the service does not require psycopg in unit tests.
    from psycopg.types.json import Jsonb
    return Jsonb(value)


def _insert(
    cursor: Any,
    *,
    source_id: str,
    station_id: str,
    variable: str,
    value: float | None,
    unit: str,
    datum: str | None,
    observed_at: datetime | None,
    quality_state: str,
    freshness_ok: bool,
    raw_payload: dict[str, Any],
    reasons: list[str],
    semantic_status: str = "PARTIAL",
    physics_eligible: bool = False,
) -> tuple[int, int]:
    if observed_at is None:
        return 0, 1
    source_record_id = f"{station_id}:{observed_at.isoformat()}"
    evidence_eligible = bool(
        quality_state in {"VALID", "VALID_ZERO"}
        and freshness_ok
        and value is not None
        and unit
        and (datum is not None or variable.startswith("RAIN_"))
    )
    payload = {
        **raw_payload,
        "semantic_status": semantic_status,
        "physics_eligible": physics_eligible,
        "evidence_eligible": evidence_eligible,
        "quality_reasons": reasons,
    }
    score = 0.8 if evidence_eligible else 0.25 if value is not None else 0.0
    cursor.execute(
        """INSERT INTO observations
           (entity_type,entity_id,variable,value,unit,datum,observed_at,source_id,source_record_id,
            quality_state,quality_score,observation_type,raw_payload)
           VALUES ('station',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OBSERVED',%s)
           ON CONFLICT (source_id,source_record_id,variable,observed_at)
             WHERE source_record_id IS NOT NULL DO NOTHING
           RETURNING observation_id,observed_at""",
        (station_id, variable, value, unit, datum, observed_at, source_id, source_record_id,
         quality_state, score, _jsonb(cursor, payload)),
    )
    row = cursor.fetchone()
    if not row:
        return 0, 1
    cursor.execute(
        """INSERT INTO observation_quality
           (observation_id,observed_at,timestamp_ok,range_ok,spike_ok,neighbour_ok,
            freshness_ok,unit_ok,datum_ok,semantics_ok,reasons)
           VALUES (%s,%s,true,%s,NULL,NULL,%s,true,%s,%s,%s)""",
        (row[0], row[1], value is not None, freshness_ok,
         True if variable.startswith("RAIN_") else bool(datum),
         semantic_status == "VERIFIED",
         _jsonb(cursor, list(reasons))),
    )
    return 1, 0


def _stage_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in snapshot.get("stations") or []:
        observed, reasons = _observed_at(item.get("observed_at_source"))
        state, fresh = _state(item.get("waterlevel_msl_m"), observed, _STAGE_MAX_AGE_HOURS)
        if item.get("waterlevel_msl_m") is None:
            continue
        rows.append({
            "source_id": "thaiwater_v3",
            "station_id": str(item.get("station_id") or item.get("station_code") or "unknown"),
            "variable": "WATER_LEVEL",
            "value": item.get("waterlevel_msl_m"),
            "unit": "m",
            "datum": "MSL",
            "observed_at": observed,
            "quality_state": state,
            "freshness_ok": fresh,
            "raw_payload": item,
            "reasons": reasons + ["THAIWATER_MSL_FIELD", "STATION_BANK_REFERENCE_IS_STATION_SCOPED"],
            # Unit/datum are explicit in the field meaning, but timestamp semantics
            # remain only partially verified, so quantitative physics stays locked.
            "semantic_status": "VERIFIED",
            "physics_eligible": False,
        })
    return rows


def _rain_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in snapshot.get("stations") or []:
        observed, reasons = _observed_at(item.get("observed_at_source"))
        station_id = str(item.get("station_id") or item.get("station_code") or "unknown")
        for field, variable in (("rain_1h_mm", "RAIN_1H"), ("rain_24h_mm", "RAIN_24H")):
            value = item.get(field)
            if value is None:
                continue
            state, fresh = _state(value, observed, _RAIN_MAX_AGE_HOURS)
            rows.append({
                "source_id": "thaiwater_rain_24h",
                "station_id": station_id,
                "variable": variable,
                "value": value,
                "unit": "mm",
                "datum": None,
                "observed_at": observed,
                "quality_state": state,
                "freshness_ok": fresh,
                "raw_payload": item,
                "reasons": reasons + ["STATION_RAINFALL_IS_CONTEXT_NOT_POINT_RAINFALL",
                                       "FLOOD_TRIGGER_THRESHOLD_NOT_CALIBRATED"],
                "semantic_status": "VERIFIED",
                "physics_eligible": False,
            })
    return rows


def persist_live_snapshots(stage_snapshot: dict[str, Any], rain_snapshot: dict[str, Any]) -> dict[str, Any]:
    database_url = configured_database_url()
    if not database_url:
        return {"persisted": False, "reason": "DATABASE_NOT_CONFIGURED"}
    try:
        import psycopg
    except ImportError:
        return {"persisted": False, "reason": "PSYCOPG_NOT_INSTALLED"}

    rows = _stage_rows(stage_snapshot) + _rain_rows(rain_snapshot)
    inserted = skipped = 0
    try:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            for row in rows:
                ins, skp = _insert(cursor, **row)
                inserted += ins
                skipped += skp
        return {"persisted": True, "inserted": inserted, "skipped_or_duplicate": skipped,
                "candidate_rows": len(rows)}
    except Exception as exc:
        return {"persisted": False, "reason": type(exc).__name__, "candidate_rows": len(rows)}


def canonical_nearby(lat: float, lon: float, kind: str, maximum_km: float = 25.0) -> list[dict[str, Any]]:
    """Read the latest evidence-eligible ThaiWater observations near a point.

    Geometry is retained in observation provenance because ThaiWater live station
    metadata is provider-owned and is not yet promoted to a hydraulically verified
    canonical station/reach mapping.
    """
    database_url = configured_database_url()
    if not database_url:
        return []
    try:
        import psycopg
    except ImportError:
        return []

    if kind == "stage":
        source_id, variables = "thaiwater_v3", ("WATER_LEVEL",)
    elif kind == "rain":
        source_id, variables = "thaiwater_rain_24h", ("RAIN_1H", "RAIN_24H")
    else:
        raise ValueError("kind must be stage or rain")

    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT DISTINCT ON (o.entity_id,o.variable)
                         o.entity_id,o.variable,o.value,o.observed_at,o.raw_payload,
                         q.timestamp_ok,q.range_ok,q.freshness_ok,q.unit_ok,q.datum_ok,q.semantics_ok
                   FROM observations o
                   JOIN observation_quality q USING (observation_id,observed_at)
                   WHERE o.source_id=%s AND o.variable = ANY(%s)
                     AND o.quality_state IN ('VALID','VALID_ZERO')
                     AND q.semantics_ok IS TRUE
                     AND o.observed_at >= now()-interval '2 hours'
                   ORDER BY o.entity_id,o.variable,o.observed_at DESC""",
                (source_id, list(variables)),
            )
            records = cursor.fetchall()
    except Exception:
        return []

    grouped: dict[str, dict[str, Any]] = {}
    for entity_id, variable, value, observed_at, raw, timestamp_ok, range_ok, freshness_ok, unit_ok, datum_ok, semantics_ok in records:
        payload = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        try:
            plat = float(payload.get("lat"))
            plon = float(payload.get("lon"))
        except (TypeError, ValueError):
            continue
        distance = math.hypot((plat - lat) * 111.0,
                              (plon - lon) * 111.0 * math.cos(math.radians(lat)))
        if distance > maximum_km:
            continue
        row = grouped.setdefault(str(entity_id), {**payload, "station_id": str(entity_id),
                                                   "distance_km_approx": round(distance, 1),
                                                   "canonical_evidence": True,
                                                   "semantics_ok": bool(semantics_ok)})
        row["observed_at_source"] = observed_at.isoformat() if observed_at else payload.get("observed_at_source")
        row["evidence_eligible"] = bool(timestamp_ok and range_ok and freshness_ok and unit_ok and datum_ok and semantics_ok)
        if variable == "WATER_LEVEL":
            row["waterlevel_msl_m"] = value
        elif variable == "RAIN_1H":
            row["rain_1h_mm"] = value
        elif variable == "RAIN_24H":
            row["rain_24h_mm"] = value
    return sorted(grouped.values(), key=lambda item: item["distance_km_approx"])


def observation_quality_summary() -> dict[str, Any]:
    database_url = configured_database_url()
    if not database_url:
        return {"available": False}
    try:
        import psycopg
    except ImportError:
        return {"available": False}
    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM observations")
            total = int(cursor.fetchone()[0])
            cursor.execute("""SELECT count(*) FROM observations o JOIN observation_quality q USING(observation_id,observed_at)
                              WHERE q.timestamp_ok IS TRUE AND q.range_ok IS TRUE AND q.freshness_ok IS TRUE
                                AND q.unit_ok IS TRUE AND q.datum_ok IS TRUE AND q.semantics_ok IS TRUE""")
            evidence_ready = int(cursor.fetchone()[0])
            cursor.execute("""SELECT count(*) FROM observations o JOIN observation_quality q USING(observation_id,observed_at)
                              WHERE q.timestamp_ok IS TRUE AND q.range_ok IS TRUE AND q.freshness_ok IS TRUE
                                AND q.unit_ok IS TRUE AND q.datum_ok IS TRUE AND q.semantics_ok IS TRUE
                                AND COALESCE((o.raw_payload->>'physics_eligible')::boolean,false) IS TRUE""")
            physics_ready = int(cursor.fetchone()[0])
            cursor.execute("""SELECT source_id,variable,count(*),max(observed_at)
                              FROM observations WHERE source_id IN ('thaiwater_v3','thaiwater_rain_24h')
                              GROUP BY source_id,variable ORDER BY source_id,variable""")
            by_source = [{"source_id": r[0], "variable": r[1], "count": int(r[2]),
                          "latest": r[3].isoformat() if r[3] else None} for r in cursor.fetchall()]
        return {"available": True, "total": total, "evidence_ready": evidence_ready,
                "physics_ready": physics_ready, "thaiwater": by_source}
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__}
