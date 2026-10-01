"""Refresh official warnings outside user-facing request paths."""

from __future__ import annotations

import asyncio
import logging

from data.connectors.providers import CONNECTORS
from scripts.ingest_common import persist_official_warnings
from app.services.sources import cache_source_health_result, record_health_results

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
            state = "VALID" if records else "VALID_ZERO"
            latest = max((record.observed_at for record in records if record.observed_at), default=None)
            freshness = "UNKNOWN"
            if latest:
                try:
                    from datetime import datetime, timezone
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest).astimezone(timezone.utc)).total_seconds()
                    freshness = "FRESH" if age <= 7200 else "STALE_CONTEXT_ONLY"
                except Exception:
                    pass
            STATE[source_id] = {"state": state, "records": len(records), "persisted": saved["inserted"]}
            result = {"status": state, "freshness": freshness, "last_observation": latest,
                      "details": {"parsed_warning_count": len(records), "background_ingest": True}}
            cache_source_health_result(source_id, result)
            record_health_results([{
                "source_id": source_id, "state": state, "freshness": freshness,
                "last_observation": latest, "checked_at": None, "details": result["details"]
            }])
        except Exception as exc:
            LOG.warning("Warning source %s unavailable: %s", source_id, type(exc).__name__)
            STATE[source_id] = {"state": "SOURCE_ERROR", "error": type(exc).__name__}
            cache_source_health_result(source_id, {"status": "SOURCE_ERROR", "freshness": "UNKNOWN",
                                                   "message": type(exc).__name__})


async def background_refresh() -> None:
    while True:
        await refresh_once()
        await asyncio.sleep(600)
