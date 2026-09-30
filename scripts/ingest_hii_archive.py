"""Download a resource discovered from the HII catalog and store safe observations."""

from __future__ import annotations

import argparse
import asyncio
import json

from data.connectors.providers import CONNECTORS
from scripts.ingest_common import persist_observations


async def run(archive_url: str, station_code: str | None) -> dict[str, object]:
    connector = CONNECTORS["hii_catalog"]
    records = await connector.fetch(archive_url=archive_url, station_code=station_code)
    observations = [item for record in records for item in connector.normalize(record)]
    return {"records": len(records), "observation_rows": len(observations), **persist_observations(observations)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-url", required=True)
    parser.add_argument("--station-code")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.archive_url, args.station_code)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
