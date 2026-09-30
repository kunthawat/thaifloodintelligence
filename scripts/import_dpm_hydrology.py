"""Import DPM main/secondary waterways as reference geometry and 22 major basins.

DPM layers contain valuable local names/geometry but do not provide a verified
NEXT_DOWN topology.  They are therefore REFERENCE_ONLY and never receive flow arrows.
"""

from __future__ import annotations

import argparse
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg
from psycopg.types.json import Jsonb

from app.settings import configured_database_url

BASE = "https://gis-portal.disaster.go.th/arcgis/rest/services/MapDX/DPM_TH_Hydrology/FeatureServer"


def _request(layer: int, **params) -> dict:
    query = {**params, "f": params.get("f", "json")}
    url = f"{BASE}/{layer}/query"
    body = urlencode(query).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={
        "User-Agent": "ThailandFloodIntelligence/0.2",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    for attempt in range(3):
        try:
            with urlopen(request, timeout=90) as response:
                payload = json.load(response)
            if "error" in payload:
                raise RuntimeError(f"DPM hydrology layer {layer}: {payload['error'].get('message')}")
            return payload
        except RuntimeError:
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError(f"DPM hydrology layer {layer}: request retries exhausted")


def _object_ids(layer: int) -> list[int]:
    return _request(layer, where="1=1", returnIdsOnly="true").get("objectIds") or []


def _import_waterways(connection, layer: int, waterway_class: str, batch_size: int = 1_000) -> int:
    ids = _object_ids(layer)
    if not ids:
        raise RuntimeError(f"DPM hydrology layer {layer} returned no IDs")
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM reference_waterways WHERE source_layer=%s AND waterway_class=%s",
                       (layer, waterway_class))
        existing_count = int(cursor.fetchone()[0])
    if existing_count == len(ids):
        print(f"DPM waterways layer {layer} already complete: {existing_count} features", flush=True)
        return existing_count
    imported = 0
    for offset in range(0, len(ids), batch_size):
        chunk = ids[offset:offset + batch_size]
        fields = "*"
        data = _request(layer, objectIds=",".join(map(str, chunk)), outFields=fields, outSR="4326", f="geojson")
        rows = []
        for feature in data.get("features") or []:
            props = feature.get("properties") or {}
            geom = feature.get("geometry")
            if not geom:
                continue
            if layer == 4:
                identity = props.get("GlobalID") or props.get("str_id") or props.get("OBJECTID")
                name_th = props.get("str_name_t")
                name_en = props.get("str_name_e")
                main_name = props.get("hy_mriver") or name_th
            else:
                identity = props.get("GlobalID") or props.get("OBJECTID_1") or props.get("OBJECTID")
                name_th = props.get("HY_LNAME")
                name_en = None
                main_name = props.get("HY_MRIVER")
            if identity is None:
                continue
            rows.append((f"DPM:{layer}:{identity}", "dpm_hydrology", layer, waterway_class,
                         str(name_th).strip() if name_th else None,
                         str(name_en).strip() if name_en else None,
                         str(main_name).strip() if main_name else None,
                         json.dumps(geom, ensure_ascii=False), Jsonb(props)))
        with connection.transaction(), connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO reference_waterways
                   (waterway_id,source_id,source_layer,waterway_class,name_th,name_en,main_river_name_th,geom,properties)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,
                     ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),2)),%s)
                   ON CONFLICT(waterway_id) DO UPDATE SET
                     name_th=EXCLUDED.name_th,name_en=EXCLUDED.name_en,
                     main_river_name_th=EXCLUDED.main_river_name_th,geom=EXCLUDED.geom,
                     properties=EXCLUDED.properties,imported_at=now()""",
                rows,
            )
        imported += len(rows)
        if imported % 25_000 < batch_size or imported == len(ids):
            print(f"DPM waterways layer {layer}: {imported}/{len(ids)}", flush=True)
    return imported


def _import_basins(connection) -> int:
    layer = 6
    ids = _object_ids(layer)
    imported = 0
    for offset in range(0, len(ids), 75):
        chunk = ids[offset:offset + 75]
        data = _request(layer, objectIds=",".join(map(str, chunk)), outFields="*", outSR="4326", f="geojson")
        rows = []
        for feature in data.get("features") or []:
            props = feature.get("properties") or {}
            geom = feature.get("geometry")
            code = props.get("รหัสลุ่มน้ำ")
            name_th = props.get("ชื่อลุ่มน้ำ")
            if not (code and name_th and geom):
                continue
            name_en = props.get("ชื่อลุ่มน้ำ_En_")
            area = props.get("พื้นที่__ตร_กม__")
            rows.append((str(code), str(name_th), str(name_en) if name_en else None,
                         float(area) if area not in (None, "") else None,
                         json.dumps(geom, ensure_ascii=False), Jsonb(props)))
        with connection.transaction(), connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO dpm_major_basins(basin_code,name_th,name_en,area_km2,geom,properties)
                   VALUES (%s,%s,%s,%s,
                     ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),3)),%s)
                   ON CONFLICT(basin_code) DO UPDATE SET name_th=EXCLUDED.name_th,name_en=EXCLUDED.name_en,
                     area_km2=EXCLUDED.area_km2,geom=EXCLUDED.geom,properties=EXCLUDED.properties,imported_at=now()""",
                rows,
            )
        imported += len(rows)
    return imported


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-basins", action="store_true")
    parser.add_argument("--only-waterways-layer", type=int, choices=(4, 5),
                        help="Import only one DPM waterways layer; layer 5 is the detailed secondary network.")
    parser.add_argument("--batch-size", type=int, default=1_000)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1_000:
        parser.error("--batch-size must be between 1 and 1000")
    url = configured_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL/DATABASE_DSN is required")
    with psycopg.connect(url, autocommit=True) as connection:
        layers = (args.only_waterways_layer,) if args.only_waterways_layer else (4, 5)
        counts = {
            layer: _import_waterways(connection, layer, "MAIN" if layer == 4 else "SECONDARY", args.batch_size)
            for layer in layers
        }
        main_count = counts.get(4, 0)
        secondary_count = counts.get(5, 0)
        basin_count = 0 if args.skip_basins else _import_basins(connection)
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE reference_waterways")
    print({"main_waterways": main_count, "secondary_waterways": secondary_count, "major_basins": basin_count})


if __name__ == "__main__":
    main()
