"""Discover and parse current-year Royal Thai Navy MSL tide predictions."""

from __future__ import annotations

import argparse
import asyncio
import json

from data.connectors.providers import CONNECTORS
from scripts.ingest_common import persist_observations


async def run(year: int, station: str | None) -> dict[str, object]:
    connector = CONNECTORS["navy_tide"]
    records = await connector.fetch(year=year, station=station or "")
    normalized = [item for record in records for item in connector.normalize(record)]
    result = persist_observations(normalized)
    return {"source_id": "navy_tide", "year": year, "station_filter": station, "records": len(records),
            "station_errors": connector.last_errors, "observation_type": "FORECAST", "physics_eligible": False, **result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--station")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.year, args.station)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
