"""Spatial context, verified HydroRIVERS topology traversal, and reference waterways.

HydroRIVERS NEXT_DOWN is the directional natural-river backbone.  DPM waterways are
reference geometry/name layers only: they improve local map context but never invent
hydraulic direction.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.settings import configured_database_url

_TERMINAL_NEXT = {None, "", "0", "-1", "None"}


def _connect():
    url = configured_database_url()
    if not url:
        raise RuntimeError("DATABASE_NOT_CONFIGURED")
    return psycopg.connect(url, connect_timeout=3, row_factory=dict_row)


def _table_exists(cursor, table: str) -> bool:
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL AS table_exists", (f"public.{table}",))
    row = cursor.fetchone()
    return bool(row and row["table_exists"])


def _nearest_reach(cursor, lat: float, lon: float, maximum_m: int = 50_000) -> dict[str, Any] | None:
    """Return the nearest HydroRIVERS edge, preferring the containing HydroBASINS catchment.

    A purely Euclidean nearest line can select a parallel but hydraulically unrelated river
    in flat floodplains.  The catchment preference is therefore part of the snap score.
    """
    latitude_delta = maximum_m / 110_000
    longitude_delta = min(
        180.0,
        maximum_m / (110_000 * max(abs(math.cos(math.radians(lat))), 1e-6)),
    )
    cursor.execute(
        """WITH p AS (
               SELECT ST_SetSRID(ST_MakePoint(%s,%s),4326) AS geom
             ), c AS (
               SELECT catchments.geom FROM catchments,p
               WHERE ST_Covers(catchments.geom,p.geom)
               ORDER BY area_km2 NULLS LAST LIMIT 1
             )
             SELECT e.edge_id::text AS edge_id,
                    e.properties->'source_fields'->>'HYRIV_ID' AS reach_id,
                    e.properties->>'next_down_provider_id' AS next_down,
                    e.properties->'source_fields'->>'MAIN_RIV' AS main_riv,
                    e.properties->'source_fields'->>'ENDORHEIC' AS endorheic,
                    round(ST_Distance(e.geom::geography,p.geom::geography)::numeric) AS distance_m,
                    e.network_confidence,e.length_m,e.direction_type::text AS direction_type,
                    ST_AsGeoJSON(e.geom)::json AS geometry,
                    CASE WHEN EXISTS (SELECT 1 FROM c WHERE ST_Intersects(e.geom,c.geom)) THEN 0 ELSE 1 END AS catchment_penalty
             FROM network_edges e,p
             WHERE e.properties->>'source'='HydroRIVERS'
               AND e.geom && ST_Expand(p.geom,%s,%s)
               AND ST_DWithin(e.geom::geography,p.geom::geography,%s)
             ORDER BY catchment_penalty, e.geom <-> p.geom
             LIMIT 1""",
        (lon, lat, longitude_delta, latitude_delta, maximum_m),
    )
    row = cursor.fetchone()
    if not row:
        return None
    result = dict(row)
    result["distance_m"] = int(result["distance_m"])
    result.pop("catchment_penalty", None)
    return result


def _nearest_reference_waterway(cursor, lat: float, lon: float, maximum_m: int = 20_000) -> dict[str, Any] | None:
    if not _table_exists(cursor, "reference_waterways"):
        return None
    cursor.execute(
        """WITH p AS (SELECT ST_SetSRID(ST_MakePoint(%s,%s),4326) AS geom)
           SELECT waterway_id,name_th,name_en,main_river_name_th,waterway_class,source_layer,
                  round(ST_Distance(reference_waterways.geom::geography,p.geom::geography)::numeric) AS distance_m,
                  ST_AsGeoJSON(reference_waterways.geom)::json AS geometry
           FROM reference_waterways,p
           WHERE ST_DWithin(reference_waterways.geom::geography,p.geom::geography,%s)
           ORDER BY reference_waterways.geom <-> p.geom LIMIT 1""",
        (lon, lat, maximum_m),
    )
    row = cursor.fetchone()
    if not row:
        return None
    result = dict(row)
    result["distance_m"] = int(result["distance_m"])
    result["topology_role"] = "REFERENCE_ONLY"
    return result


def location_context(lat: float, lon: float) -> dict[str, Any]:
    point = "ST_SetSRID(ST_MakePoint(%s,%s),4326)"
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT catchment_id,area_km2,properties->>'PFAF_ID' AS pfaf_id,
                           properties->>'NEXT_DOWN' AS next_down
                    FROM catchments WHERE ST_Covers(geom,{point})
                    ORDER BY area_km2 NULLS LAST LIMIT 1""",
                (lon, lat),
            )
            catchment = cursor.fetchone()
            reach = _nearest_reach(cursor, lat, lon)
            reference = _nearest_reference_waterway(cursor, lat, lon)
    except (psycopg.Error, RuntimeError):
        return {
            "catchment": None,
            "nearest_reach": None,
            "nearest_reference_waterway": None,
            "network_confidence": None,
            "availability": {"available": False, "reason": "DATABASE_UNAVAILABLE"},
        }
    return {
        "catchment": dict(catchment) if catchment else None,
        "nearest_reach": reach,
        "nearest_reference_waterway": reference,
        "network_confidence": reach["network_confidence"] if reach else None,
        "availability": {
            "available": bool(catchment or reach or reference),
            "reason": None if catchment or reach or reference else "LOCATION_OUTSIDE_IMPORTED_COVERAGE",
        },
    }


def _edge_by_reach_id(cursor, reach_id: str) -> dict[str, Any] | None:
    cursor.execute(
        """SELECT edge_id::text AS edge_id,from_node_id::text AS from_node_id,to_node_id::text AS to_node_id,
                  length_m,network_confidence,direction_type::text AS direction_type,
                  properties->'source_fields'->>'HYRIV_ID' AS reach_id,
                  properties->>'next_down_provider_id' AS next_down,
                  properties->'source_fields'->>'MAIN_RIV' AS main_riv,
                  properties->'source_fields'->>'ENDORHEIC' AS endorheic,
                  properties->'source_fields'->>'UPLAND_SKM' AS upland_skm,
                  ST_AsGeoJSON(geom)::json AS geometry
           FROM network_edges
           WHERE properties->>'source'='HydroRIVERS'
             AND properties->'source_fields'->>'HYRIV_ID'=%s
           LIMIT 1""",
        (reach_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _incoming_edges(cursor, downstream_reach_ids: list[str], remaining: int) -> list[dict[str, Any]]:
    if not downstream_reach_ids or remaining <= 0:
        return []
    cursor.execute(
        """SELECT edge_id::text AS edge_id,from_node_id::text AS from_node_id,to_node_id::text AS to_node_id,
                  length_m,network_confidence,direction_type::text AS direction_type,
                  properties->'source_fields'->>'HYRIV_ID' AS reach_id,
                  properties->>'next_down_provider_id' AS next_down,
                  properties->'source_fields'->>'MAIN_RIV' AS main_riv,
                  properties->'source_fields'->>'ENDORHEIC' AS endorheic,
                  properties->'source_fields'->>'UPLAND_SKM' AS upland_skm,
                  ST_AsGeoJSON(geom)::json AS geometry
           FROM network_edges
           WHERE properties->>'source'='HydroRIVERS'
             AND properties->>'next_down_provider_id'=ANY(%s)
           ORDER BY COALESCE(NULLIF(properties->'source_fields'->>'UPLAND_SKM','')::double precision,0) DESC,
                    length_m DESC NULLS LAST
           LIMIT %s""",
        (downstream_reach_ids, remaining),
    )
    return [dict(row) for row in cursor.fetchall()]


def _line_endpoints(geometry: dict[str, Any] | None) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if not geometry:
        return None
    coords = geometry.get("coordinates")
    if geometry.get("type") == "LineString" and coords and len(coords) >= 2:
        return (tuple(coords[0][:2]), tuple(coords[-1][:2]))
    if geometry.get("type") == "MultiLineString" and coords and coords[0] and coords[-1]:
        return (tuple(coords[0][0][:2]), tuple(coords[-1][-1][:2]))
    return None


def _reverse_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    if geometry.get("type") == "LineString":
        return {**geometry, "coordinates": list(reversed(geometry.get("coordinates") or []))}
    if geometry.get("type") == "MultiLineString":
        parts = geometry.get("coordinates") or []
        return {**geometry, "coordinates": [list(reversed(part)) for part in reversed(parts)]}
    return geometry


def _dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _downstream_oriented_geometry(row: dict[str, Any], by_reach: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    geometry = row.get("geometry")
    ends = _line_endpoints(geometry)
    downstream = by_reach.get(str(row.get("next_down") or ""))
    down_ends = _line_endpoints(downstream.get("geometry") if downstream else None)
    if not geometry or not ends or not down_ends:
        return geometry
    start, end = ends
    downstream_candidates = down_ends
    start_distance = min(_dist2(start, point) for point in downstream_candidates)
    end_distance = min(_dist2(end, point) for point in downstream_candidates)
    # The line end should touch/approach the next-down reach.  Reverse only for rendering;
    # source geometry is not mutated in PostGIS.
    return _reverse_geometry(geometry) if start_distance < end_distance else geometry


def _feature_collection(reaches: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    by_reach = {str(row.get("reach_id")): row for row in reaches if row.get("reach_id")}
    features = []
    for row in reaches:
        geometry = _downstream_oriented_geometry(row, by_reach)
        if not geometry:
            continue
        features.append({
            "type": "Feature",
            "id": row["edge_id"],
            "geometry": geometry,
            "properties": {
                "reach_id": row.get("reach_id"),
                "next_down": row.get("next_down"),
                "depth": row.get("depth", 0),
                "branch": row.get("branch"),
                "length_m": row.get("length_m"),
                "network_confidence": row.get("network_confidence"),
                "route_direction": direction,
                "topology_role": "HYDRORIVERS_NEXT_DOWN",
                "render_direction": "DOWNSTREAM",
            },
        })
    return {"type": "FeatureCollection", "features": features}


def river_route(lat: float, lon: float, direction: str, limit: int = 80) -> dict[str, Any]:
    """Traverse verified source topology instead of arbitrary graph-neighbour LIMIT 1.

    Downstream follows HydroRIVERS NEXT_DOWN deterministically to the terminal reach.
    Upstream performs a bounded breadth-first traversal and keeps tributary branches.
    """
    if direction not in {"upstream", "downstream"}:
        raise ValueError("direction must be upstream or downstream")
    try:
        with _connect() as connection, connection.cursor() as cursor:
            first = _nearest_reach(cursor, lat, lon)
            if not first or first["distance_m"] > 50_000:
                return {"available": False, "reason": "NO_NEARBY_VERIFIED_RIVER", "reaches": [],
                        "network_confidence": None, "route_geojson": _feature_collection([], direction)}

            reaches: list[dict[str, Any]] = []
            visited: set[str] = set()
            terminal: dict[str, Any] | None = None

            if direction == "downstream":
                current = _edge_by_reach_id(cursor, first["reach_id"])
                depth = 0
                while current and len(reaches) < limit:
                    reach_id = str(current.get("reach_id") or "")
                    if not reach_id or reach_id in visited:
                        break
                    visited.add(reach_id)
                    current["depth"] = depth
                    current["branch"] = 0
                    reaches.append(current)
                    next_id = current.get("next_down")
                    if next_id in _TERMINAL_NEXT:
                        terminal = {
                            "reach_id": reach_id,
                            "type": "INLAND_SINK" if str(current.get("endorheic") or "0") not in {"0", "", "None"} else "OCEAN_OR_TERMINAL_OUTLET",
                            "verified_from": "HydroRIVERS NEXT_DOWN",
                        }
                        break
                    current = _edge_by_reach_id(cursor, str(next_id))
                    depth += 1
            else:
                first_row = _edge_by_reach_id(cursor, first["reach_id"])
                if first_row:
                    first_row["depth"] = 0
                    first_row["branch"] = 0
                    reaches.append(first_row)
                    visited.add(str(first_row.get("reach_id")))
                frontier = [first["reach_id"]]
                depth = 1
                branch_counter = 0
                while frontier and len(reaches) < limit:
                    rows = _incoming_edges(cursor, frontier, limit - len(reaches))
                    next_frontier: list[str] = []
                    for row in rows:
                        rid = str(row.get("reach_id") or "")
                        if not rid or rid in visited:
                            continue
                        visited.add(rid)
                        branch_counter += 1
                        row["depth"] = depth
                        row["branch"] = branch_counter
                        reaches.append(row)
                        next_frontier.append(rid)
                    frontier = next_frontier
                    depth += 1

    except psycopg.Error:
        return {"available": False, "reason": "NETWORK_QUERY_FAILED", "reaches": [],
                "network_confidence": None, "route_geojson": _feature_collection([], direction)}

    min_conf = min((float(r["network_confidence"] or 0) for r in reaches), default=0.0)
    total_length = sum(float(r.get("length_m") or 0) for r in reaches)
    return {
        "available": bool(reaches),
        "reason": None if reaches else "NO_VERIFIED_ROUTE",
        "reaches": reaches,
        "route_geojson": _feature_collection(reaches, direction),
        "reach_count": len(reaches),
        "total_length_m": total_length,
        "network_confidence": min_conf if reaches else None,
        "source": "HydroRIVERS",
        "direction_type": "SOURCE_TOPOLOGY_NEXT_DOWN",
        "hydraulic_travel_time_available": False,
        "terminal": terminal,
        "truncated": bool(len(reaches) >= limit),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _downstream_relation(cursor, start_id: str, target_id: str, max_hops: int = 250) -> bool:
    current = start_id
    visited: set[str] = set()
    for _ in range(max_hops):
        if current == target_id:
            return True
        if current in visited:
            return False
        visited.add(current)
        row = _edge_by_reach_id(cursor, current)
        if not row or row.get("next_down") in _TERMINAL_NEXT:
            return False
        current = str(row["next_down"])
    return False


def hydraulic_station_links(lat: float, lon: float, stations: list[dict[str, Any]],
                            station_snap_m: int = 12_000) -> list[dict[str, Any]]:
    """Classify station-to-location topology without pretending same-catchment means connected."""
    if not stations:
        return []
    try:
        with _connect() as connection, connection.cursor() as cursor:
            target = _nearest_reach(cursor, lat, lon)
            if not target:
                return []
            results: list[dict[str, Any]] = []
            for station in stations:
                try:
                    slat, slon = float(station["lat"]), float(station["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                station_reach = _nearest_reach(cursor, slat, slon, maximum_m=station_snap_m)
                if not station_reach:
                    continue
                relation = "CATCHMENT_CONTEXT"
                if station_reach["reach_id"] == target["reach_id"]:
                    relation = "CONNECTED_SAME_REACH"
                elif _downstream_relation(cursor, station_reach["reach_id"], target["reach_id"]):
                    relation = "CONNECTED_UPSTREAM"
                elif _downstream_relation(cursor, target["reach_id"], station_reach["reach_id"]):
                    relation = "CONNECTED_DOWNSTREAM"
                elif station_reach.get("main_riv") and station_reach.get("main_riv") == target.get("main_riv"):
                    relation = "SAME_RIVER_SYSTEM_CONTEXT"
                results.append({
                    **station,
                    "hydraulic_relation": relation,
                    "station_reach_id": station_reach["reach_id"],
                    "target_reach_id": target["reach_id"],
                    "station_snap_distance_m": station_reach["distance_m"],
                })
            return results
    except (psycopg.Error, RuntimeError):
        return []


def network_features(west: float, south: float, east: float, north: float, limit: int = 1_500) -> list[dict[str, Any]]:
    bbox = "ST_MakeEnvelope(%s,%s,%s,%s,4326)"
    wide_view = (east - west) > 3 or (north - south) > 3
    # HydroRIVERS is the regional natural-river topology. At town/city scale,
    # give most of the display budget to the finer DPM reference waterways.
    hydro_limit = max(200, int(limit * 0.65)) if wide_view else max(100, int(limit * 0.15))
    reference_limit = max(120, limit - hydro_limit)
    hydro_simplify_tolerance = 0.0015 if wide_view else 0.00015
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT edge_id::text AS id,
                       ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom,%s))::json AS geometry,
                       network_confidence,
                       properties->'source_fields'->>'HYRIV_ID' AS reach_id,
                       NULL::text AS name_th,
                       'HydroRIVERS'::text AS source,
                       'HYDRORIVERS_NEXT_DOWN'::text AS topology_role
                FROM network_edges
                WHERE properties->>'source'='HydroRIVERS'
                  AND geom && {bbox} AND ST_Intersects(geom,{bbox})
                ORDER BY COALESCE(NULLIF(properties->'source_fields'->>'UPLAND_SKM','')::double precision,0) DESC,
                         length_m DESC NULLS LAST LIMIT %s""",
            (hydro_simplify_tolerance, west, south, east, north, west, south, east, north, hydro_limit),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        if _table_exists(cursor, "reference_waterways"):
            class_filter = "AND waterway_class='MAIN'" if wide_view else ""
            cursor.execute(
                f"""SELECT waterway_id AS id,
                           ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom,0.0001))::json AS geometry,
                           0.55::double precision AS network_confidence,
                           NULL::text AS reach_id,name_th,'DPM'::text AS source,
                           'REFERENCE_ONLY'::text AS topology_role,waterway_class
                    FROM reference_waterways
                    WHERE geom && {bbox} AND ST_Intersects(geom,{bbox}) {class_filter}
                    ORDER BY CASE waterway_class WHEN 'MAIN' THEN 0 ELSE 1 END,
                             ST_Length(geom) DESC
                    LIMIT %s""",
                (west, south, east, north, west, south, east, north, reference_limit),
            )
            rows.extend(dict(row) for row in cursor.fetchall())
            for row in rows:
                row.setdefault("waterway_class", "NATURAL_RIVER_TOPOLOGY")
        return rows


def station_record(identifier: str) -> dict[str, Any] | None:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT station_id::text AS station_id,canonical_code,canonical_name_th,
                      canonical_name_en,river_or_waterway,province,district,subdistrict,
                      ST_X(geom) AS longitude,ST_Y(geom) AS latitude,active,
                      metadata_confidence,properties
               FROM stations
               WHERE station_id::text=%s OR canonical_code=%s LIMIT 1""",
            (identifier, identifier),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
