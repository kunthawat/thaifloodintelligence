"""Apply each numbered PostGIS migration exactly once, in order."""

from __future__ import annotations

from app.settings import configured_database_url


def main() -> None:
    database_url = configured_database_url()
    if not database_url:
        raise SystemExit("Set DATABASE_URL or DATABASE_DSN to an authorized PostgreSQL/PostGIS database first.")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Install dependencies with psycopg before applying migrations.") from exc

    from pathlib import Path

    migration_dir = Path(__file__).resolve().parent / "migrations"
    migrations = sorted(migration_dir.glob("[0-9]*.sql"))
    if not migrations:
        raise SystemExit("No SQL migrations found.")

    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtext('thailand-flood-intelligence-migrations'))")
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            cursor.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cursor.fetchall()}

        try:
            for migration in migrations:
                version = migration.name
                if version in applied:
                    continue
                sql = migration.read_text(encoding="utf-8")
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(sql, prepare=False)
                        cursor.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))
                print(f"Applied {version}")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtext('thailand-flood-intelligence-migrations'))")


if __name__ == "__main__":
    main()
