"""Bulk import full Asia HydroBASINS and HydroRIVERS with pyogrio and PostGIS."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any, Iterator

from app.settings import configured_database_url


def _database():
    import psycopg

    url = configured_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL or DATABASE_DSN is required for vector import")
    return psycopg.connect(url, autocommit=True)


def _native(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _batches(path: Path, feature_count: int, size: int = 3000) -> Iterator[tuple[Any, Any, Any]]:
    from pyogrio.raw import read

    for offset in range(0, feature_count, size):
        meta, _, geometries, columns = read(path, skip_features=offset, max_features=size)
        if geometries is None or len(geometries) == 0:
            raise ValueError(f"{path.name}: missing features at offset {offset}")
        yield meta["fields"], geometries, columns


def _props(fields: Any, columns: Any, index: int) -> dict[str, Any]:
    return {str(field): _native(column[index]) for field, column in zip(fields, columns)}


def _field(properties: dict[str, Any], name: str) -> Any:
    return next((value for key, value in properties.items() if key.upper() == name), None)


def _version(cursor: Any, source_id: str, vector_files: list[Path], details: dict[str, Any]) -> None:
    from psycopg.types.json import Jsonb

    digest = hashlib.sha256()
    for path in sorted(vector_files):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    cursor.execute(
        """INSERT INTO source_schema_versions(source_id,schema_version,valid_from,schema_definition,parser_version)
           VALUES (%s,%s,now(),%s,'2') ON CONFLICT(source_id,schema_version) DO NOTHING""",
        (source_id, f"sha256:{digest.hexdigest()}", Jsonb({**details, "source_files": [path.name for path in vector_files]})),
    )


def _copy_basins_file(connection: Any, path: Path, level: int, feature_count: int, epsg: int) -> int:
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE hydro_basins_stage")
            copied = 0
            with cursor.copy("COPY hydro_basins_stage (basin_id,level,area_km2,epsg,wkb,properties) FROM STDIN") as copy:
                for fields, geometries, columns in _batches(path, feature_count):
                    for index, geometry in enumerate(geometries):
                        props = _props(fields, columns, index)
                        basin_id = _field(props, "HYBAS_ID")
                        area = _field(props, "SUB_AREA")
                        if basin_id is None or geometry is None:
                            raise ValueError(f"{path.name}: HYBAS_ID or geometry is missing")
                        copy.write_row((str(basin_id), level, float(area) if area is not None else None,
                                        epsg, bytes(geometry), json.dumps(props, ensure_ascii=False)))
                        copied += 1
            if copied != feature_count:
                raise ValueError(f"{path.name}: expected {feature_count} features, copied {copied}")
            cursor.execute(
                """INSERT INTO basins(basin_id,name_en,source,source_id,level,geom,properties)
                   SELECT basin_id,NULL,'HydroBASINS','hydrobasins',level,
                          ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromWKB(wkb),epsg),4326)),properties
                   FROM hydro_basins_stage
                   ON CONFLICT (basin_id) DO UPDATE SET source=EXCLUDED.source,source_id=EXCLUDED.source_id,
                     level=EXCLUDED.level,geom=EXCLUDED.geom,properties=EXCLUDED.properties"""
            )
            if level in {8, 9, 10}:
                cursor.execute(
                    """INSERT INTO catchments(catchment_id,basin_id,source,source_id,area_km2,transboundary,geom,properties)
                       SELECT basin_id,basin_id,'HydroBASINS','hydrobasins',area_km2,false,
                              ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromWKB(wkb),epsg),4326)),
                              properties || '{"transboundary_status":"NOT_EVALUATED; preserve Asia geometry and upstream topology"}'::jsonb
                       FROM hydro_basins_stage
                       ON CONFLICT (catchment_id) DO UPDATE SET area_km2=EXCLUDED.area_km2,
                         geom=EXCLUDED.geom,properties=EXCLUDED.properties"""
                )
    return copied


def import_hydrobasins(report: dict[str, Any]) -> dict[str, Any]:
    if not report.get("valid"):
        raise ValueError("HydroBASINS CRS, fields or source archive did not pass validation")
    vector_files = [Path(item["path"]) for item in report["vector_files"]]
    by_level: dict[int, tuple[Path, dict[str, Any]]] = {}
    for item in report["vector_files"]:
        path = Path(item["path"])
        matched = re.search(r"lev(\d{2})", path.stem, re.I)
        if not matched:
            raise ValueError(f"Cannot verify HydroBASINS level in {path.name}")
        level = int(matched.group(1))
        if level in by_level:
            raise ValueError(f"Duplicate HydroBASINS level {level}")
        by_level[level] = path, item
    if set(by_level) != set(range(1, 13)):
        raise ValueError(f"Full Asia HydroBASINS levels 1-12 are required; found {sorted(by_level)}")

    counts: dict[int, int] = {}
    with _database() as connection:
        connection.execute(
            """CREATE TEMP TABLE hydro_basins_stage (
                 basin_id text, level integer, area_km2 double precision, epsg integer,
                 wkb bytea, properties jsonb) ON COMMIT PRESERVE ROWS"""
        )
        for level in range(1, 13):
            path, item = by_level[level]
            counts[level] = _copy_basins_file(connection, path, level, int(item["feature_count"]), int(item["epsg"]))
            print(f"HydroBASINS level {level}: {counts[level]} features imported", flush=True)
        with connection.transaction():
            with connection.cursor() as cursor:
                _version(cursor, "hydrobasins", vector_files, {"levels": counts, "extent_import": "full Asia; no country clipping"})
    return {"source_id": "hydrobasins", "basin_levels": counts, "rows": sum(counts.values()), "extent_import": "full Asia"}


_TERMINAL = {"0", "-1", "", "None"}


def _stage_rivers(connection: Any, path: Path, feature_count: int, epsg: int) -> int:
    with connection.cursor() as cursor:
        copied = 0
        with cursor.copy(
            "COPY hydro_rivers_stage (reach_id,next_id,length_m,epsg,wkb,properties,node_id,edge_id,outlet_id) FROM STDIN"
        ) as copy:
            for fields, geometries, columns in _batches(path, feature_count, size=6000):
                for index, geometry in enumerate(geometries):
                    props = _props(fields, columns, index)
                    reach_id = _field(props, "HYRIV_ID")
                    next_down = _field(props, "NEXT_DOWN")
                    length_km = _field(props, "LENGTH_KM")
                    if reach_id is None or next_down is None or geometry is None:
                        raise ValueError(f"{path.name}: HydroRIVERS ID, NEXT_DOWN or geometry is missing")
                    reach, next_id = str(reach_id), str(next_down)
                    copy.write_row((reach, next_id, float(length_km) * 1000 if length_km is not None else None,
                                    epsg, bytes(geometry), json.dumps(props, ensure_ascii=False),
                                    uuid.uuid5(uuid.NAMESPACE_URL, f"hydrorivers:reach:{reach}"),
                                    uuid.uuid5(uuid.NAMESPACE_URL, f"hydrorivers:edge:{reach}"),
                                    uuid.uuid5(uuid.NAMESPACE_URL, f"hydrorivers:outlet:{reach}") if next_id in _TERMINAL else None))
                    copied += 1
                if copied % 120000 < len(geometries):
                    print(f"HydroRIVERS staged {copied}/{feature_count} reaches", flush=True)
        return copied


def import_hydrorivers(report: dict[str, Any]) -> dict[str, Any]:
    if not report.get("valid") or len(report.get("vector_files", [])) != 1:
        raise ValueError("One complete Asia HydroRIVERS shapefile is required")
    item = report["vector_files"][0]
    path = Path(item["path"])
    feature_count, epsg = int(item["feature_count"]), int(item["epsg"])
    with _database() as connection:
        connection.execute(
            """CREATE TEMP TABLE hydro_rivers_stage (
                 reach_id text, next_id text, length_m double precision, epsg integer,
                 wkb bytea, properties jsonb, node_id uuid, edge_id uuid, outlet_id uuid)
                 ON COMMIT PRESERVE ROWS"""
        )
        copied = _stage_rivers(connection, path, feature_count, epsg)
        if copied != feature_count:
            raise ValueError(f"HydroRIVERS feature count mismatch: {copied} vs {feature_count}")
        print("HydroRIVERS validating source topology", flush=True)
        connection.execute("CREATE UNIQUE INDEX hydro_rivers_stage_reach_idx ON hydro_rivers_stage(reach_id)")
        absent = connection.execute(
            """SELECT count(*) FROM hydro_rivers_stage s LEFT JOIN hydro_rivers_stage d ON s.next_id=d.reach_id
               WHERE s.next_id NOT IN ('0','-1','') AND d.reach_id IS NULL"""
        ).fetchone()[0]
        if absent:
            raise ValueError(f"HydroRIVERS Asia product has {absent} NEXT_DOWN targets absent from the imported product")
        print("HydroRIVERS importing nodes and edges", flush=True)
        with connection.transaction():
            connection.execute(
                """INSERT INTO network_nodes(node_id,node_type,provider,provider_id,geom,confidence,properties)
                   SELECT node_id,'JUNCTION','HydroRIVERS',reach_id,
                     ST_Transform(ST_StartPoint(ST_GeometryN(ST_SetSRID(ST_GeomFromWKB(wkb),epsg),1)),4326),0.35,
                     jsonb_build_object('source_fields',properties,'topology_status','source-derived; hydraulic direction remains dynamic')
                   FROM hydro_rivers_stage
                   ON CONFLICT (node_id) DO UPDATE SET geom=EXCLUDED.geom,properties=EXCLUDED.properties"""
            )
            connection.execute(
                """INSERT INTO network_nodes(node_id,node_type,provider,provider_id,geom,confidence,properties)
                   SELECT outlet_id,'OUTLET','HydroRIVERS','outlet:' || reach_id,
                     ST_Transform(ST_EndPoint(ST_GeometryN(ST_SetSRID(ST_GeomFromWKB(wkb),epsg),
                       ST_NumGeometries(ST_GeomFromWKB(wkb)))),4326),0.35,
                     jsonb_build_object('source_reach_id',reach_id,'topology_status','natural-river terminal in source product')
                   FROM hydro_rivers_stage WHERE outlet_id IS NOT NULL
                   ON CONFLICT (node_id) DO UPDATE SET geom=EXCLUDED.geom,properties=EXCLUDED.properties"""
            )
            connection.execute(
                """INSERT INTO network_edges(edge_id,edge_type,from_node_id,to_node_id,direction_type,
                        geom,length_m,network_confidence,hydraulic_parameters_verified,properties)
                   SELECT s.edge_id,'RIVER_REACH',s.node_id,COALESCE(d.node_id,s.outlet_id),'DYNAMIC',
                     ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromWKB(s.wkb),s.epsg),4326)),
                     s.length_m,0.35,false,
                     jsonb_build_object('source','HydroRIVERS','source_id','hydrorivers',
                         'source_fields',s.properties,'next_down_provider_id',s.next_id,
                         'hydraulic_parameters_verified',false,'artificial_canal',false)
                   FROM hydro_rivers_stage s LEFT JOIN hydro_rivers_stage d ON s.next_id=d.reach_id
                   ON CONFLICT (edge_id) DO UPDATE SET from_node_id=EXCLUDED.from_node_id,to_node_id=EXCLUDED.to_node_id,
                     direction_type='DYNAMIC',geom=EXCLUDED.geom,length_m=EXCLUDED.length_m,
                     network_confidence=EXCLUDED.network_confidence,hydraulic_parameters_verified=false,
                     properties=EXCLUDED.properties"""
            )
            with connection.cursor() as cursor:
                _version(cursor, "hydrorivers", [path], {"reach_count": copied, "topology_field": "NEXT_DOWN", "artificial_canal_inference": False})
        outlet_count = connection.execute("SELECT count(*) FROM hydro_rivers_stage WHERE outlet_id IS NOT NULL").fetchone()[0]
    return {"source_id": "hydrorivers", "reaches": copied, "nodes": copied + outlet_count,
            "network_confidence": 0.35, "direction_type": "DYNAMIC", "hydraulic_parameters_verified": False}
