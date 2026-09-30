"""Import official DPM province, amphoe and tambon polygons into PostGIS."""

from __future__ import annotations

import json
import argparse
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg

from app.settings import configured_database_url

BASE = "https://gis-portal.disaster.go.th/arcgis/rest/services/MapDX/DPM_TH_Boundary/FeatureServer"
LAYERS = (
    (1, "admin_province", ("PROV_CODE", "PROV_NAM_T")),
    (2, "admin_amphoe", ("AMP_CODE", "PROV_CODE", "PROV_NAM_T", "AMP_NAM_T")),
    (3, "admin_tambon", ("TAM_CODE", "AMP_CODE", "PROV_CODE", "PROV_NAM_T", "AMP_NAM_T", "TAM_NAM_T")),
)
FIELDS = {
    "admin_province": ("prov_code", "prov_name_th"),
    "admin_amphoe": ("amp_code", "prov_code", "prov_name_th", "amp_name_th"),
    "admin_tambon": ("tam_code", "amp_code", "prov_code", "prov_name_th", "amp_name_th", "tam_name_th"),
}


def _request(layer: int, **params) -> dict:
    url = f"{BASE}/{layer}/query?" + urlencode({**params, "f": params.pop("f", "json")})
    with urlopen(Request(url, headers={"User-Agent": "ThailandFloodIntelligence/0.1"}), timeout=45) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"DPM layer {layer}: {payload['error'].get('message')}")
    return payload


def _import_layer(connection: psycopg.Connection, layer: int, table: str, source_fields: tuple[str, ...]) -> int:
    ids = _request(layer, where="1=1", returnIdsOnly="true").get("objectIds") or []
    if not ids:
        raise RuntimeError(f"DPM layer {layer} returned no IDs")
    columns = FIELDS[table]
    placeholders = ",".join(["%s"] * len(columns))
    names = ",".join(columns)
    primary = columns[0]
    updates = ",".join(f"{name}=EXCLUDED.{name}" for name in columns[1:])
    merged_geom = (f"ST_Multi(ST_CollectionExtract(ST_UnaryUnion(ST_Collect({table}.geom,"
                   "EXCLUDED.geom)),3))" if table == "admin_tambon" else "EXCLUDED.geom")
    sql = (f"INSERT INTO {table} ({names},geom,source_url) VALUES ({placeholders},"
           "ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),3)),%s) "
           f"ON CONFLICT ({primary}) DO UPDATE SET {updates},geom={merged_geom},"
           "source_url=EXCLUDED.source_url,imported_at=now()")
    imported = 0
    seen: dict[str, tuple[str, ...]] = {}
    for offset in range(0, len(ids), 75):
        chunk = ids[offset:offset + 75]
        data = _request(layer, objectIds=",".join(map(str, chunk)), outFields=",".join(source_fields),
                        outSR="4326", f="geojson")
        features = data.get("features") or []
        if len(features) != len(chunk):
            raise RuntimeError(f"DPM layer {layer}: expected {len(chunk)} shapes, got {len(features)}")
        rows = []
        for feature in features:
            properties = feature.get("properties") or {}
            values = [str(properties.get(field) or "").strip() for field in source_fields]
            if not all(values) or not feature.get("geometry"):
                raise RuntimeError(f"DPM layer {layer}: missing required code/name/geometry")
            if values[0] in seen and seen[values[0]] != tuple(values[1:]):
                raise RuntimeError(f"DPM layer {layer}: code {values[0]} maps to different names")
            seen[values[0]] = tuple(values[1:])
            rows.append((*values, json.dumps(feature["geometry"], ensure_ascii=False), f"{BASE}/{layer}"))
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.executemany(sql, rows)
        imported += len(rows)
        print(f"{table}: {imported}/{len(ids)}", flush=True)
    return imported


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", type=int, choices=(1, 2, 3))
    args = parser.parse_args()
    url = configured_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    with psycopg.connect(url, autocommit=True) as connection:
        for layer, table, source_fields in LAYERS:
            if args.layer and layer != args.layer:
                continue
            count = _import_layer(connection, layer, table, source_fields)
            print(f"Imported {table}: {count}", flush=True)


if __name__ == "__main__":
    main()
