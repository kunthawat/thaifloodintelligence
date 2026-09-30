"""Run bounded health checks against enabled public source endpoints."""

from __future__ import annotations

import asyncio
import json

from app.services.sources import record_health_results, refresh_source_health


async def run() -> dict[str, object]:
    rows = await refresh_source_health(force=True)
    return {"source_health": rows, "database_persistence": record_health_results(rows)}


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
