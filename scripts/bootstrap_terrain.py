"""Resolve, download, validate and register HydroSHEDS Asia terrain inputs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from data.connectors.static import StaticHydroConnector


async def run(region: str, resolution: str) -> dict[str, object]:
    if region.casefold() != "asia" or resolution.casefold() not in {"3s", "3sec", "3-second", "3 arc-second"}:
        raise SystemExit("The manifest defines HydroSHEDS Asia at 3 arc-second resolution only.")
    os.environ["HYDROSHEDS_REGION"] = "Asia"
    os.environ["HYDROSHEDS_RESOLUTION"] = "3s"
    connector = StaticHydroConnector("hydrosheds")
    discovery = await connector.discover_version()
    if discovery.status != "VALID":
        raise SystemExit(f"Could not resolve the official Asia 3s DEM/DIR/ACC download links: {json.dumps(discovery.details)}")
    files = await connector.download(discovery)
    report = connector.validate(files)
    if not report.get("valid"):
        raise SystemExit(f"HydroSHEDS input validation failed: {json.dumps(report)}")
    registration = connector.import_dataset(files)
    return {"discovery": discovery.details, "files": files, "validation": report, "registration": registration}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="asia")
    parser.add_argument("--resolution", default="3s")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.region, args.resolution)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
