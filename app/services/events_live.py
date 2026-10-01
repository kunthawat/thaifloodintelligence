"""Read persisted hydrologic events/waves without creating synthetic events."""

from __future__ import annotations

from typing import Any
import psycopg
from psycopg.rows import dict_row
from app.settings import configured_database_url


def _connect():
    url=configured_database_url()
    if not url: raise RuntimeError("DATABASE_NOT_CONFIGURED")
    return psycopg.connect(url, connect_timeout=3, row_factory=dict_row)


def waves_near_location(lat: float, lon: float, limit: int = 30) -> dict[str, Any]:
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT w.wave_id::text,w.event_id::text,w.state::text,w.generated_at,w.eta_start,w.eta_p50,w.eta_end,
                                     w.confidence,e.canonical_name,
                                     ST_Distance(e.geom::geography,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) AS distance_m
                              FROM event_waves w
                              JOIN network_edges e ON e.edge_id=w.current_edge_id
                              JOIN hydrologic_events h ON h.event_id=w.event_id
                              WHERE h.state <> 'ENDED'
                                AND ST_DWithin(e.geom::geography,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,100000)
                              ORDER BY distance_m LIMIT %s""", (lon,lat,lon,lat,limit))
            rows=[dict(r) for r in cursor.fetchall()]
    except (psycopg.Error, RuntimeError):
        return {"events": [], "available": False, "reason": "EVENT_DATABASE_UNAVAILABLE"}
    for row in rows:
        for key in ("generated_at","eta_start","eta_p50","eta_end"):
            if row.get(key): row[key]=row[key].isoformat()
    return {"events": rows, "available": bool(rows),
            "reason": None if rows else "NO_TRACKED_ACTIVE_WAVES_NEAR_LOCATION"}


def event_record(event_id: str) -> dict[str, Any] | None:
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT event_id::text,canonical_name,dominant_hazard::text,state::text,origin_catchment_id,
                                     started_at,ended_at,official_warning_present,properties
                              FROM hydrologic_events WHERE event_id::text=%s""", (event_id,))
            event=cursor.fetchone()
            if not event: return None
            cursor.execute("""SELECT wave_id::text,parent_wave_id::text,state::text,origin_catchment_id,current_edge_id::text,
                                     generated_at,eta_start,eta_p50,eta_end,peak_q_p10,peak_q_p50,peak_q_p90,confidence,properties
                              FROM event_waves WHERE event_id::text=%s ORDER BY generated_at NULLS LAST""", (event_id,))
            waves=[dict(r) for r in cursor.fetchall()]
    except (psycopg.Error, RuntimeError):
        return None
    result=dict(event)
    for key in ("started_at","ended_at"):
        if result.get(key): result[key]=result[key].isoformat()
    for row in waves:
        for key in ("generated_at","eta_start","eta_p50","eta_end"):
            if row.get(key): row[key]=row[key].isoformat()
    result["waves"]=waves
    return result
