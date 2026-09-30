"""Read only spatial views of verified HydroBASINS and HydroRIVERS data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.settings import configured_database_url


def _connect():
    url = configured_database_url()
    if not url:
        raise RuntimeError("DATABASE_NOT_CONFIGURED")
    return psycopg.connect(url, connect_timeout=3, row_factory=dict_row)


def location_context(lat: float, lon: float) -> dict[str, Any]:
    point = "ST_SetSRID(ST_MakePoint(%s,%s),4326)"
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""SELECT catchment_id,area_km2,properties->>'PFAF_ID' AS pfaf_id,
                               properties->>'NEXT_DOWN' AS next_down
                        FROM catchments WHERE ST_Covers(geom,{point})
                        ORDER BY area_km2 NULLS LAST LIMIT 1""",
                    (lon, lat),
                )
                catchment = cursor.fetchone()
                cursor.execute(
                    f"""SELECT edge_id::text AS edge_id,properties->>'source' AS source,
                               properties->'source_fields'->>'HYRIV_ID' AS reach_id,
                               properties->>'next_down_provider_id' AS next_down,
                               round(ST_Distance(geom::geography,{point}::geography)::numeric) AS distance_m,
                               network_confidence,length_m,direction_type::text AS direction_type
                        FROM network_edges ORDER BY geom <-> {point} LIMIT 1""",
                    (lon, lat, lon, lat),
                )
                reach = cursor.fetchone()
    except (psycopg.Error, RuntimeError):
        return {"catchment": None, "nearest_reach": None, "network_confidence": None,
                "availability": {"available": False, "reason": "DATABASE_UNAVAILABLE"}}
    if reach:
        reach["distance_m"] = int(reach["distance_m"])
    return {
        "catchment": dict(catchment) if catchment else None,
        "nearest_reach": dict(reach) if reach else None,
        "network_confidence": reach["network_confidence"] if reach else None,
        "availability": {"available": bool(catchment or reach),
                         "reason": None if catchment or reach else "LOCATION_OUTSIDE_IMPORTED_COVERAGE"},
    }


def river_route(lat: float, lon: float, direction: str, limit: int = 20) -> dict[str, Any]:
    context = location_context(lat, lon)
    first = context.get("nearest_reach")
    if not first or first["distance_m"] > 50_000:
        return {"available": False, "reason": "NO_NEARBY_VERIFIED_RIVER", "reaches": [],
                "network_confidence": None}
    ids = [first["edge_id"]]
    reaches: list[dict[str, Any]] = []
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                for _ in range(limit):
                    if direction == "downstream":
                        cursor.execute(
                            """SELECT edge_id::text AS edge_id,from_node_id::text AS from_node_id,
                                      to_node_id::text AS to_node_id,length_m,network_confidence,
                                      properties->'source_fields'->>'HYRIV_ID' AS reach_id,
                                      properties->>'next_down_provider_id' AS next_down
                               FROM network_edges WHERE edge_id=%s::uuid""", (ids[-1],))
                    else:
                        cursor.execute(
                            """SELECT edge_id::text AS edge_id,from_node_id::text AS from_node_id,
                                      to_node_id::text AS to_node_id,length_m,network_confidence,
                                      properties->'source_fields'->>'HYRIV_ID' AS reach_id,
                                      properties->>'next_down_provider_id' AS next_down
                               FROM network_edges WHERE edge_id=%s::uuid""", (ids[-1],))
                    row = cursor.fetchone()
                    if not row:
                        break
                    reaches.append(row)
                    node = row["to_node_id"] if direction == "downstream" else row["from_node_id"]
                    key = "from_node_id" if direction == "downstream" else "to_node_id"
                    cursor.execute(f"SELECT edge_id::text FROM network_edges WHERE {key}=%s::uuid AND edge_id<>%s::uuid LIMIT 1", (node, row["edge_id"]))
                    next_row = cursor.fetchone()
                    if not next_row or next_row["edge_id"] in ids:
                        break
                    ids.append(next_row["edge_id"])
    except psycopg.Error:
        return {"available": False, "reason": "NETWORK_QUERY_FAILED", "reaches": [],
                "network_confidence": None}
    return {"available": bool(reaches), "reason": None if reaches else "NO_VERIFIED_ROUTE",
            "reaches": reaches, "network_confidence": min((r["network_confidence"] or 0) for r in reaches) if reaches else None,
            "source": "HydroRIVERS", "direction_type": "SOURCE_TOPOLOGY_ONLY",
            "hydraulic_travel_time_available": False,
            "generated_at": datetime.now(timezone.utc).isoformat()}


def network_features(west: float, south: float, east: float, north: float, limit: int = 200) -> list[dict[str, Any]]:
    bbox = "ST_MakeEnvelope(%s,%s,%s,%s,4326)"
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT edge_id::text AS id,ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom,0.004))::json AS geometry,
                           network_confidence,properties->'source_fields'->>'HYRIV_ID' AS reach_id
                    FROM network_edges WHERE geom && {bbox}
                    ORDER BY length_m DESC NULLS LAST LIMIT %s""",
                (west, south, east, north, limit),
            )
            return list(cursor.fetchall())


def station_record(identifier: str) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT station_id::text AS station_id,canonical_code,canonical_name_th,
                          canonical_name_en,river_or_waterway,province,district,subdistrict,
                          CASE WHEN geom IS NOT NULL THEN ST_Y(geom) END AS latitude,
                          CASE WHEN geom IS NOT NULL THEN ST_X(geom) END AS longitude,
                          active,metadata_confidence,properties
                   FROM stations WHERE station_id::text=%s OR canonical_code=%s LIMIT 1""",
                (identifier, identifier),
            )
            station = cursor.fetchone()
            if not station:
                return None
            cursor.execute(
                """SELECT source_id,provider_station_code,provider_station_id,provider_station_name,
                          mapping_status,verified_at,verification_method,notes
                   FROM station_source_map WHERE station_id=%s::uuid ORDER BY source_id""",
                (station["station_id"],),
            )
            mappings = list(cursor.fetchall())
            cursor.execute(
                """SELECT DISTINCT ON(variable) variable,value,unit,datum,observed_at,source_id,
                          quality_state::text AS quality_state,observation_type::text AS observation_type
                   FROM observations WHERE entity_type='STATION' AND entity_id IN (%s,%s)
                   ORDER BY variable,observed_at DESC""",
                (station["station_id"], station["canonical_code"]),
            )
            observations = list(cursor.fetchall())
    return {**station, "source_mappings": mappings, "latest_observations": observations,
            "current_observation_available": bool(observations)}
