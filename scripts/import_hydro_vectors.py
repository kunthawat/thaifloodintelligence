"""Import full Asia HydroBASINS/HydroRIVERS topology into PostGIS."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Iterator

from app.settings import configured_database_url


def _drivers() -> tuple[Any, Any]:
    try:
        from osgeo import ogr
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("Install GDAL/OGR Python bindings and psycopg before importing vector products") from exc
    return ogr, Jsonb


def _connection():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install psycopg before importing vector products") from exc
    url = configured_database_url()
    if not url:
        raise RuntimeError("Set DATABASE_URL or DATABASE_DSN before importing datasets")
    return psycopg.connect(url)


def _properties(feature: Any) -> dict[str, Any]:
    definition = feature.GetDefnRef()
    values = {}
    for index in range(definition.GetFieldCount()):
        name = definition.GetFieldDefn(index).GetName()
        value = feature.GetField(index)
        values[name] = value
    return values


def _field(properties: dict[str, Any], *names: str) -> Any:
    values = {str(key).upper(): value for key, value in properties.items()}
    for name in names:
        if name.upper() in values:
            return values[name.upper()]
    return None


def _json_geometry(feature: Any) -> str:
    geometry = feature.GetGeometryRef()
    if geometry is None:
        raise ValueError("vector feature is missing its geometry")
    return geometry.ExportToJson()


def _source_epsg(layer: Any) -> int:
    spatial_ref = layer.GetSpatialRef()
    epsg = int(spatial_ref.GetAuthorityCode(None)) if spatial_ref and spatial_ref.GetAuthorityCode(None) else 0
    if epsg not in {4326, 4269}:
        raise ValueError(f"unexpected vector CRS EPSG:{epsg}")
    return epsg


def _insert_schema_version(cursor: Any, source_id: str, files: list[Path], properties: dict[str, Any]) -> None:
    hasher = hashlib.sha256()
    for path in sorted(files):
        hasher.update(path.name.encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
    version = f"sha256:{hasher.hexdigest()}"
    from psycopg.types.json import Jsonb
    cursor.execute(
        """INSERT INTO source_schema_versions(source_id,schema_version,valid_from,schema_definition,parser_version)
           VALUES (%s,%s,now(),%s,'1') ON CONFLICT(source_id,schema_version) DO NOTHING""",
        (source_id, version, Jsonb({**properties, "source_files": [path.name for path in files]})),
    )


def import_hydrobasins(report: dict[str, Any]) -> dict[str, Any]:
    ogr, Jsonb = _drivers()
    vector_files = [Path(item["path"]) for item in report.get("vector_files", [])]
    if not report.get("valid") or not vector_files:
        raise ValueError("HydroBASINS files did not pass CRS, geometry and topology validation")
    counts: dict[int, int] = {}
    with _connection() as connection:
        with connection.cursor() as cursor:
            for path in vector_files:
                dataset = ogr.Open(str(path), 0)
                if dataset is None:
                    raise ValueError(f"Cannot open {path.name}")
                layer = dataset.GetLayer(0)
                epsg = _source_epsg(layer)
                filename_level = re.search(r"(?:lev|level)[_-]?(\d{1,2})", path.stem, re.I)
                for feature in layer:
                    props = _properties(feature)
                    basin_id = _field(props, "HYBAS_ID")
                    if basin_id is None:
                        raise ValueError(f"{path.name}: missing HYBAS_ID")
                    level = _field(props, "LEVEL")
                    level = int(level) if level is not None else int(filename_level.group(1)) if filename_level else None
                    if level not in range(1, 13):
                        raise ValueError(f"{path.name}: HydroBASINS level could not be verified as 1-12")
                    name_en = _field(props, "NAME_EN", "NAME")
                    cursor.execute(
                        """INSERT INTO basins(basin_id,name_en,source,source_id,level,geom,properties)
                           VALUES (%s,%s,'HydroBASINS','hydrobasins',%s,
                             ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s),%s),4326)),%s)
                           ON CONFLICT (basin_id) DO UPDATE SET name_en=EXCLUDED.name_en,
                             source=EXCLUDED.source,source_id=EXCLUDED.source_id,level=EXCLUDED.level,
                             geom=EXCLUDED.geom,properties=EXCLUDED.properties""",
                        (str(basin_id), str(name_en) if name_en is not None else None, level, _json_geometry(feature), epsg, Jsonb(props)),
                    )
                    if level in {8, 9, 10}:
                        area = _field(props, "SUB_AREA", "AREA_SQKM", "CATCH_SKM")
                        cursor.execute(
                            """INSERT INTO catchments
                               (catchment_id,basin_id,source,source_id,area_km2,transboundary,geom,properties)
                               VALUES (%s,%s,'HydroBASINS','hydrobasins',%s,false,
                                 ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s),%s),4326)),%s)
                               ON CONFLICT (catchment_id) DO UPDATE SET basin_id=EXCLUDED.basin_id,
                                 area_km2=EXCLUDED.area_km2,geom=EXCLUDED.geom,properties=EXCLUDED.properties""",
                            (str(basin_id), str(basin_id), float(area) if area is not None else None,
                             _json_geometry(feature), epsg,
                             Jsonb({**props, "transboundary_status": "NOT_EVALUATED; preserve Asia geometry and upstream topology"})),
                        )
                    counts[level] = counts.get(level, 0) + 1
            missing = set(range(1, 13)) - set(counts)
            if missing:
                raise ValueError(f"Full Asia HydroBASINS import requires levels 1-12; missing {sorted(missing)}")
            _insert_schema_version(cursor, "hydrobasins", vector_files, {"levels": counts, "extent_import": "full source files; no Thailand-border clipping"})
    return {"source_id": "hydrobasins", "basin_levels": counts, "rows": sum(counts.values()), "extent_import": "full source files"}


def import_hydrorivers(report: dict[str, Any]) -> dict[str, Any]:
    ogr, Jsonb = _drivers()
    vector_files = [Path(item["path"]) for item in report.get("vector_files", [])]
    if not report.get("valid") or not vector_files:
        raise ValueError("HydroRIVERS files did not pass CRS, geometry and topology validation")
    rows: list[dict[str, Any]] = []
    for path in vector_files:
        dataset = ogr.Open(str(path), 0)
        if dataset is None:
            raise ValueError(f"Cannot open {path.name}")
        layer = dataset.GetLayer(0)
        epsg = _source_epsg(layer)
        for feature in layer:
            props = _properties(feature)
            reach_id = _field(props, "HYRIV_ID")
            next_down = _field(props, "NEXT_DOWN")
            if reach_id is None or next_down is None:
                raise ValueError(f"{path.name}: HydroRIVERS topology fields are missing")
            geometry = json.loads(_json_geometry(feature))
            coords = _line_ends(geometry)
            rows.append({"id": str(reach_id), "next": str(next_down), "props": props, "geometry": geometry, "ends": coords, "epsg": epsg})
    if not rows:
        raise ValueError("HydroRIVERS Asia file contained no reaches")
    known = {row["id"] for row in rows}
    absent_downstream = sorted({row["next"] for row in rows if row["next"] not in {"0", "", "None"} and row["next"] not in known})
    if absent_downstream:
        raise ValueError(f"HydroRIVERS topology is incomplete: {len(absent_downstream)} NEXT_DOWN targets are absent from the imported Asia product")

    node_ids = {row["id"]: uuid.uuid5(uuid.NAMESPACE_URL, f"hydrorivers:reach:{row['id']}") for row in rows}
    outlet_ids = {row["id"]: uuid.uuid5(uuid.NAMESPACE_URL, f"hydrorivers:outlet:{row['id']}") for row in rows if row["next"] in {"0", "", "None"}}
    with _connection() as connection:
        with connection.cursor() as cursor:
            for row in rows:
                lon, lat = row["ends"][0]
                cursor.execute(
                    """INSERT INTO network_nodes(node_id,node_type,canonical_name,provider,provider_id,geom,confidence,properties)
                       VALUES (%s,'JUNCTION',NULL,'HydroRIVERS',%s,
                         ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),%s),4326),0.35,%s)
                       ON CONFLICT (node_id) DO UPDATE SET geom=EXCLUDED.geom,properties=EXCLUDED.properties""",
                    (node_ids[row["id"]], row["id"], lon, lat, row["epsg"], Jsonb({"source_fields": row["props"], "topology_status": "NEXT_DOWN verifies topological downstream; realtime hydraulic direction is not verified"})),
                )
                if row["id"] in outlet_ids:
                    end_lon, end_lat = row["ends"][1]
                    cursor.execute(
                        """INSERT INTO network_nodes(node_id,node_type,provider,provider_id,geom,confidence,properties)
                           VALUES (%s,'OUTLET','HydroRIVERS',%s,
                             ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),%s),4326),0.35,%s)
                           ON CONFLICT (node_id) DO UPDATE SET geom=EXCLUDED.geom,properties=EXCLUDED.properties""",
                        (outlet_ids[row["id"]], f"outlet:{row['id']}", end_lon, end_lat, row["epsg"], Jsonb({"source_reach_id": row["id"], "topology_status": "natural-river terminal in source product"})),
                    )
            for row in rows:
                target_id = outlet_ids[row["id"]] if row["id"] in outlet_ids else node_ids[row["next"]]
                reach = str(_field(row["props"], "HYRIV_ID"))
                length = _field(row["props"], "LENGTH_KM")
                edge_id = uuid.uuid5(uuid.NAMESPACE_URL, f"hydrorivers:edge:{reach}")
                cursor.execute(
                    """INSERT INTO network_edges(edge_id,edge_type,canonical_name,from_node_id,to_node_id,direction_type,
                        geom,length_m,network_confidence,hydraulic_parameters_verified,properties)
                       VALUES (%s,'RIVER_REACH',NULL,%s,%s,'FORWARD',
                         ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s),%s),4326)),%s,0.35,false,%s)
                       ON CONFLICT (edge_id) DO UPDATE SET from_node_id=EXCLUDED.from_node_id,to_node_id=EXCLUDED.to_node_id,
                         direction_type='FORWARD',geom=EXCLUDED.geom,length_m=EXCLUDED.length_m,
                         network_confidence=EXCLUDED.network_confidence,hydraulic_parameters_verified=false,properties=EXCLUDED.properties""",
                    (edge_id, node_ids[reach], target_id, json.dumps(row["geometry"]), row["epsg"], float(length) * 1000 if length is not None else None,
                     Jsonb({"source": "HydroRIVERS", "source_id": "hydrorivers", "source_fields": row["props"], "next_down_provider_id": row["next"], "topology_direction_verified": True, "realtime_hydraulic_direction_verified": False, "hydraulic_parameters_verified": False, "artificial_canal": False})),
                )
            _insert_schema_version(cursor, "hydrorivers", vector_files, {"reach_count": len(rows), "topology_field": "NEXT_DOWN", "artificial_canal_inference": False})
    return {"source_id": "hydrorivers", "reaches": len(rows), "nodes": len(node_ids) + len(outlet_ids), "network_confidence": 0.35, "direction_type": "FORWARD", "hydraulic_parameters_verified": False}


def _line_ends(geometry: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]]:
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "LineString" and coordinates and len(coordinates) >= 2:
        return (tuple(coordinates[0][:2]), tuple(coordinates[-1][:2]))
    if geometry.get("type") == "MultiLineString" and coordinates and coordinates[0] and len(coordinates[0]) >= 2:
        return (tuple(coordinates[0][0][:2]), tuple(coordinates[-1][-1][:2]))
    raise ValueError("HydroRIVERS reach geometry is not a valid line")
