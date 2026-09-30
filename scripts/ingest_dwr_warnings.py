"""Ingest parseable DWR EWS warnings without treating them as H/Q forcing."""

from __future__ import annotations

import asyncio
import json

from data.connectors.providers import CONNECTORS
from scripts.ingest_common import persist_official_warnings


async def run() -> dict[str, object]:
    connector = CONNECTORS["dwr_ews_warnings"]
    records = await connector.fetch()
    saved = persist_official_warnings(records)
    return {"source_id": connector.source_id, "parsed_warning_rows": len(records), "forcing_eligible": False,
            "empty_result_proves_no_warning": False, **saved}


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
