"""Ensure the lightweight DPM main-river reference layer is available at startup."""
from __future__ import annotations

import subprocess
import sys

import psycopg

from app.settings import configured_database_url


def main() -> None:
    url = configured_database_url()
    if not url:
        raise SystemExit("DATABASE_URL/DATABASE_DSN is required")
    with psycopg.connect(url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.reference_waterways') IS NOT NULL")
        if not cursor.fetchone()[0]:
            raise SystemExit("Run database migrations before DPM hydrology import")
        cursor.execute("SELECT count(*) FROM reference_waterways WHERE source_layer=4")
        count = int(cursor.fetchone()[0])
    if count:
        print(f"DPM hydrology already imported: {count} reference waterways")
        return
    # The nationwide DPM secondary network contains about 850k features. Keep
    # application startup fast and load that versioned reference layer explicitly.
    subprocess.run([sys.executable, "-m", "scripts.import_dpm_hydrology",
                    "--only-waterways-layer", "4", "--skip-basins"], check=True)


if __name__ == "__main__":
    main()
