"""Optional PostGIS health check without silently substituting another store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.settings import configured_database_url


def database_status() -> dict[str, Any]:
    database_url = configured_database_url()
    if not database_url:
        return {
            "state": "NOT_CONFIGURED",
            "detail": "DATABASE_URL or DATABASE_DSN is not set; no local fallback database is used.",
        }
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError:
        return {
            "state": "DRIVER_NOT_INSTALLED",
            "detail": "Install the psycopg dependency before configuring a PostgreSQL connection.",
        }
    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT PostGIS_Version()")
                row = cursor.fetchone()
                cursor.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
                has_migrations = bool(cursor.fetchone()[0])
                migration_count = 0
                applied_versions: set[str] = set()
                if has_migrations:
                    cursor.execute("SELECT version FROM schema_migrations")
                    applied_versions = {str(item[0]) for item in cursor.fetchall()}
                    migration_count = len(applied_versions)
                migration_dir = Path(__file__).resolve().parents[2] / "db" / "migrations"
                expected_versions = {path.name for path in migration_dir.glob("[0-9]*.sql")}
                migrations_ready = bool(expected_versions) and expected_versions.issubset(applied_versions)
                missing_migrations = sorted(expected_versions - applied_versions)
                counts: dict[str, int] = {}
                for table, key in (("basins", "basin_count"), ("network_edges", "network_edge_count"),
                                   ("terrain_products", "terrain_product_count"),
                                   ("admin_province", "admin_province_count"),
                                   ("admin_amphoe", "admin_amphoe_count"),
                                   ("admin_tambon", "admin_tambon_count"),
                                   ("reference_waterways", "reference_waterway_count"),
                                   ("dpm_major_basins", "dpm_major_basin_count")):
                    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
                    if cursor.fetchone()[0]:
                        cursor.execute(f"SELECT count(*) FROM {table}")
                        counts[key] = int(cursor.fetchone()[0])
                    else:
                        counts[key] = 0
                cursor.execute("""SELECT count(*) FROM official_warnings
                                  WHERE issued_at >= now()-interval '2 hours'
                                    AND (valid_to IS NULL OR valid_to >= now()) AND geom IS NOT NULL""")
                counts["scoped_current_warning_count"] = int(cursor.fetchone()[0])
                cursor.execute("SELECT to_regclass('public.observations') IS NOT NULL")
                if cursor.fetchone()[0]:
                    cursor.execute("SELECT count(*) FROM observations")
                    counts["observation_count"] = int(cursor.fetchone()[0])
                    cursor.execute("SELECT count(*) FROM observations WHERE source_id='thaiwater_v3' AND variable='WATER_LEVEL'")
                    counts["thaiwater_stage_observation_count"] = int(cursor.fetchone()[0])
                    cursor.execute("SELECT count(*) FROM observations WHERE source_id='thaiwater_rain_24h' AND variable IN ('RAIN_1H','RAIN_24H')")
                    counts["thaiwater_rain_observation_count"] = int(cursor.fetchone()[0])
                    cursor.execute("""SELECT count(*) FROM observations o
                                      JOIN observation_quality q USING(observation_id,observed_at)
                                      WHERE o.source_id='thaiwater_v3' AND o.variable='WATER_LEVEL'
                                        AND o.observed_at BETWEEN now()-interval '2 hours' AND now()+interval '5 minutes'
                                        AND o.quality_state IN ('VALID','VALID_ZERO')
                                        AND q.timestamp_ok IS TRUE AND q.range_ok IS TRUE AND q.freshness_ok IS TRUE
                                        AND q.unit_ok IS TRUE AND q.datum_ok IS TRUE AND q.semantics_ok IS TRUE""")
                    counts["thaiwater_stage_evidence_ready_count"] = int(cursor.fetchone()[0])
                    cursor.execute("""SELECT count(*) FROM observations o
                                      JOIN observation_quality q USING(observation_id,observed_at)
                                      WHERE o.source_id='thaiwater_rain_24h' AND o.variable IN ('RAIN_1H','RAIN_24H')
                                        AND o.observed_at BETWEEN now()-interval '2 hours' AND now()+interval '5 minutes'
                                        AND o.quality_state IN ('VALID','VALID_ZERO')
                                        AND q.timestamp_ok IS TRUE AND q.range_ok IS TRUE AND q.freshness_ok IS TRUE
                                        AND q.unit_ok IS TRUE AND q.datum_ok IS TRUE AND q.semantics_ok IS TRUE""")
                    counts["thaiwater_rain_evidence_ready_count"] = int(cursor.fetchone()[0])
                    cursor.execute("""SELECT count(*) FROM observations o
                                      JOIN observation_quality q USING(observation_id,observed_at)
                                      WHERE q.timestamp_ok IS TRUE AND q.range_ok IS TRUE
                                        AND q.freshness_ok IS TRUE AND q.unit_ok IS TRUE AND q.datum_ok IS TRUE
                                        AND q.semantics_ok IS TRUE""")
                    counts["observation_evidence_ready_count"] = int(cursor.fetchone()[0])
                    cursor.execute("""SELECT count(*) FROM observations o
                                      JOIN observation_quality q USING(observation_id,observed_at)
                                      WHERE q.timestamp_ok IS TRUE AND q.range_ok IS TRUE
                                        AND q.freshness_ok IS TRUE AND q.unit_ok IS TRUE AND q.datum_ok IS TRUE
                                        AND q.semantics_ok IS TRUE
                                        AND COALESCE((o.raw_payload->>'physics_eligible')::boolean,false) IS TRUE""")
                    counts["observation_physics_ready_count"] = int(cursor.fetchone()[0])
                    cursor.execute("""SELECT max(observed_at) FILTER (WHERE source_id='thaiwater_v3'),
                                             max(observed_at) FILTER (WHERE source_id='thaiwater_rain_24h')
                                      FROM observations""")
                    latest_stage, latest_rain = cursor.fetchone()
                    counts["thaiwater_stage_latest"] = latest_stage.isoformat() if latest_stage else None
                    counts["thaiwater_rain_latest"] = latest_rain.isoformat() if latest_rain else None
                else:
                    counts.update({
                        "observation_count": 0,
                        "thaiwater_stage_observation_count": 0,
                        "thaiwater_rain_observation_count": 0,
                        "thaiwater_stage_evidence_ready_count": 0,
                        "thaiwater_rain_evidence_ready_count": 0,
                        "observation_evidence_ready_count": 0,
                        "observation_physics_ready_count": 0,
                        "thaiwater_stage_latest": None,
                        "thaiwater_rain_latest": None,
                    })
        return {
            "state": "READY",
            "postgis_version": row[0] if row else None,
            "migrations_applied": migration_count,
            "migrations_ready": migrations_ready,
            "missing_migrations": missing_migrations,
            **counts,
        }
    except Exception as exc:  # health reporting must never prevent the API from serving its safe state
        return {"state": "UNAVAILABLE", "detail": str(exc.__class__.__name__)}
