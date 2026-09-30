"""Import DPM hydrology once when reference waterways are absent."""
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
        cursor.execute("SELECT count(*) FROM reference_waterways")
        count = int(cursor.fetchone()[0])
    if count:
        print(f"DPM hydrology already imported: {count} reference waterways")
        return
    subprocess.run([sys.executable, "-m", "scripts.import_dpm_hydrology"], check=True)


if __name__ == "__main__":
    main()
