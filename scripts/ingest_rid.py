"""Ingest current large-dam and medium-reservoir state while locking out raw flows."""

from __future__ import annotations

import asyncio
import json

from data.connectors.providers import CONNECTORS
from scripts.ingest_common import persist_observations


async def run() -> dict[str, object]:
    result: dict[str, object] = {"sources": {}}
    for source_id in ("rid_dam", "rid_reservoir"):
        connector = CONNECTORS[source_id]
        records = await connector.fetch()
        normalized = [item for record in records for item in connector.normalize(record)]
        stored = persist_observations(normalized)
        result["sources"][source_id] = {
            "records": len(records), "canonical_observations": len(normalized), **stored,
            "semantics": connector.validate_semantics().__dict__,
        }
    return result


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
