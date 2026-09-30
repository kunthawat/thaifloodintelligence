"""Discover the current official HII water-level archive catalog."""

from __future__ import annotations

import asyncio
import json

from data.connectors.providers import CONNECTORS
from scripts.ingest_common import persist_catalog_schema


async def run() -> dict[str, object]:
    discovery = await CONNECTORS["hii_catalog"].discover()
    resources = list(discovery.resources)
    if discovery.status != "VALID":
        raise SystemExit(f"HII catalog discovery failed: {discovery.details}")
    saved = persist_catalog_schema("hii_catalog", resources)
    return {"source_id": "hii_catalog", "discovered_resources": len(resources), **saved}


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
