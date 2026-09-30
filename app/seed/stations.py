"""Load the manifest station seeds without promoting candidate IDs."""

from __future__ import annotations

from pathlib import Path

from app.settings import ROOT, configured_database_url

SOURCE_MAP = {
    "HII": ["hii_catalog"],
    "HII legacy": ["hii_legacy_graph"],
    "DWR EWS": ["dwr_ews_station"],
    "HII archive": ["hii_catalog"],
    # The manifest does not resolve these records to a particular provider;
    # keep their canonical stations without fabricating provider mappings.
    "multi-source": [],
}


def main() -> None:
    database_url = configured_database_url()
    if not database_url:
        raise SystemExit("Set DATABASE_URL or DATABASE_DSN before seeding stations.")
    try:
        import psycopg
        import yaml
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit("Install psycopg and PyYAML before seeding stations.") from exc

    seed_path = ROOT / "config" / "station_seeds.yaml"
    payload = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
    stations = payload.get("stations") or []
    if not stations:
        raise SystemExit("No station seeds were found.")
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            for station in stations:
                canonical_code = str(station["canonical_code"])
                properties = dict(station)
                # A bank reference marked for reconfirmation stays metadata and
                # is not inserted into bank_references as an eligible threshold.
                cursor.execute(
                    """INSERT INTO stations
                       (canonical_code,canonical_name_th,canonical_name_en,river_or_waterway,
                        province,district,subdistrict,active,metadata_confidence,properties)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,true,%s,%s)
                       ON CONFLICT (canonical_code) DO UPDATE SET
                         canonical_name_th=EXCLUDED.canonical_name_th,
                         canonical_name_en=EXCLUDED.canonical_name_en,
                         river_or_waterway=EXCLUDED.river_or_waterway,
                         province=EXCLUDED.province,district=EXCLUDED.district,
                         subdistrict=EXCLUDED.subdistrict,properties=EXCLUDED.properties""",
                    (canonical_code, station.get("canonical_name_th"), station.get("canonical_name_en"),
                     station.get("river_or_waterway"), station.get("province"), station.get("district"),
                     station.get("subdistrict"), 0.3, Jsonb(properties)),
                )
                cursor.execute("SELECT station_id FROM stations WHERE canonical_code=%s", (canonical_code,))
                station_id = cursor.fetchone()[0]
                mapping_status = str(station.get("mapping_status", "UNRESOLVED"))
                if mapping_status == "VERIFIED_CODE":
                    mapping_status = "VERIFIED"
                provider_code = station.get("provider_station_code")
                candidate = mapping_status in {"CANDIDATE_REQUIRES_NAME_MATCH", "CONFLICT"}
                provider_id = None if candidate else station.get("provider_station_id")
                for source_id in SOURCE_MAP.get(str(station.get("source", "")), []):
                    notes = station.get("notes", "") or ""
                    if candidate and station.get("provider_station_id"):
                        notes = f"{notes} Candidate provider ID {station['provider_station_id']} is not persisted until exact identity verification.".strip()
                    cursor.execute(
                        """INSERT INTO station_source_map
                           (station_id,source_id,provider_station_code,provider_station_id,mapping_status,
                            verified_at,verification_method,notes)
                           VALUES (%s,%s,%s,%s,%s,NULL,%s,%s)
                           ON CONFLICT DO NOTHING""",
                        (station_id, source_id, provider_code, provider_id, mapping_status,
                         "manifest seed; requires runtime verification" if candidate or "NAME_ONLY" in mapping_status else "manifest seed", notes),
                    )
    print(f"Seeded {len(stations)} canonical stations and safe source mappings.")


if __name__ == "__main__":
    main()
