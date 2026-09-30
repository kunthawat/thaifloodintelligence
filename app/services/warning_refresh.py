"""Refresh official warnings outside user-facing request paths."""

from __future__ import annotations

import asyncio
import logging

from data.connectors.providers import CONNECTORS
from scripts.ingest_common import persist_official_warnings

LOG = logging.getLogger(__name__)
STATE: dict[str, dict] = {}


async def refresh_once() -> None:
    for source_id in ("dwr_ews_warnings", "hii_public_warning"):
        connector = CONNECTORS[source_id]
        if not connector.definition.enabled():
            STATE[source_id] = {"state": "NOT_CONFIGURED", "records": 0}
            continue
        try:
            records = await asyncio.wait_for(connector.fetch(), timeout=18)
            saved = await asyncio.to_thread(persist_official_warnings, records) if records else {"inserted": 0}
            STATE[source_id] = {"state": "VALID" if records else "VALID_ZERO",
                                "records": len(records), "persisted": saved["inserted"]}
        except Exception as exc:
            LOG.warning("Warning source %s unavailable: %s", source_id, type(exc).__name__)
            STATE[source_id] = {"state": "SOURCE_ERROR", "error": type(exc).__name__}


async def background_refresh() -> None:
    while True:
        await refresh_once()
        await asyncio.sleep(600)
