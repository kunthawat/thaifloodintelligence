"""Create private host-side settings for the portable PostGIS runtime."""

from __future__ import annotations

import secrets
from pathlib import Path

from app.settings import ROOT


def main() -> None:
    env_file = ROOT / ".env"
    password_file = ROOT / "local_runtime" / "pgpassword.txt"
    if env_file.exists() or password_file.exists():
        if not env_file.exists() or not password_file.exists():
            raise SystemExit("Existing local settings are incomplete; resolve .env and pgpassword.txt together.")
        print("Existing private local settings preserved.")
        return

    password = secrets.token_urlsafe(32)
    settings = {
        "PUBLIC_BASE_URL": "http://127.0.0.1:8899",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "5432",
        "POSTGRES_PASSWORD": password,
        "DATABASE_URL": f"postgresql+psycopg://thai_flood:{password}@127.0.0.1:5432/thai_flood",
        "DATABASE_DSN": f"postgresql://thai_flood:{password}@127.0.0.1:5432/thai_flood",
        "DATA_DIR": "data",
        "STATIC_DATA_DIR": "data/static",
        "RAW_DATA_DIR": "data/raw",
        "CACHE_DATA_DIR": "data/cache",
        "RASTER_DATA_DIR": "data/rasters",
        "MODEL_DATA_DIR": "data/models",
    }
    source = (ROOT / ".env.example").read_text(encoding="utf-8")
    seen: set[str] = set()
    lines = []
    for line in source.splitlines():
        key, separator, _ = line.partition("=")
        if separator and key in settings:
            lines.append(f"{key}={settings[key]}")
            seen.add(key)
        else:
            lines.append(line)
    if seen != settings.keys():
        raise SystemExit(f".env.example is missing: {sorted(settings.keys() - seen)}")
    password_file.parent.mkdir(parents=True, exist_ok=True)
    password_file.write_text(password + "\n", encoding="utf-8")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Created private local settings in {env_file} and {password_file}.")


if __name__ == "__main__":
    main()
