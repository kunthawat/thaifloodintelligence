"""Optional PostGIS health check without silently substituting another store."""

from __future__ import annotations

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
                if has_migrations:
                    cursor.execute("SELECT count(*) FROM schema_migrations")
                    migration_count = int(cursor.fetchone()[0])
                counts: dict[str, int] = {}
                for table, key in (("basins", "basin_count"), ("network_edges", "network_edge_count"),
                                   ("terrain_products", "terrain_product_count"),
                                   ("admin_province", "admin_province_count"),
                                   ("admin_amphoe", "admin_amphoe_count"),
                                   ("admin_tambon", "admin_tambon_count")):
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
        return {
            "state": "READY",
            "postgis_version": row[0] if row else None,
            "migrations_applied": migration_count,
            "migrations_ready": migration_count >= 14,
            **counts,
        }
    except Exception as exc:  # health reporting must never prevent the API from serving its safe state
        return {"state": "UNAVAILABLE", "detail": str(exc.__class__.__name__)}
