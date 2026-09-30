"""Download, validate and import full Asia HydroBASINS levels 1-12."""

from __future__ import annotations

import argparse
import asyncio
import json

from data.connectors.static import StaticHydroConnector


async def run() -> dict[str, object]:
    connector = StaticHydroConnector("hydrobasins")
    discovery = await connector.discover_version()
    if discovery.status != "VALID":
        raise SystemExit(f"Could not resolve an official HydroBASINS Asia download: {json.dumps(discovery.details)}")
    files = await connector.download(discovery)
    report = connector.validate(files)
    if not report.get("valid"):
        raise SystemExit(f"HydroBASINS validation failed: {json.dumps(report)}")
    return {"discovery": discovery.details, "files": files, "validation": report, "import": connector.import_dataset(files)}


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
