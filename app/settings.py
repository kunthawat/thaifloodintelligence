"""Small environment loader and shared path/config helpers."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    """Read a local .env without overriding values exported by the process."""
    env_path = path or ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def configured_database_url() -> str | None:
    load_dotenv()
    url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_DSN") or os.getenv("THAI_FLOOD_DATABASE_URL")
    if not url:
        return None
    # The manifest provides SQLAlchemy's driver-qualified URL for app config;
    # psycopg takes the equivalent native libpq scheme.
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def data_path(variable: str, default: str) -> Path:
    load_dotenv()
    configured = Path(os.getenv(variable, default)).expanduser()
    return configured if configured.is_absolute() else ROOT / configured
