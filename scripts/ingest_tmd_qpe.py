"""Discover and archive the current TMD QPE ASCII grid without guessing units."""

from __future__ import annotations

import asyncio
import json

from data.connectors.providers import CONNECTORS


async def run() -> dict[str, object]:
    records = await CONNECTORS["tmd_qpe_ascii"].fetch()
    return {"source_id": "tmd_qpe_ascii", "records": [record.payload for record in records],
            "rainfall_physics_eligible": False, "reason": "QPE grid units remain unverified unless the discovered payload explicitly documents them"}


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
