"""Refresh and persist public ThaiWater station observations outside request paths."""

from __future__ import annotations

import asyncio
import logging

from app.services.live_observation_ingest import persist_live_snapshots
from app.services.rainfall_live import snapshot as rainfall_snapshot
from app.services.waterlevel_live import snapshot as waterlevel_snapshot

LOG = logging.getLogger(__name__)


async def refresh_once() -> dict[str, object]:
    snapshots: dict[str, dict] = {}
    for name, func in (("waterlevel", waterlevel_snapshot), ("rainfall", rainfall_snapshot)):
        try:
            snapshots[name] = await asyncio.to_thread(func)
        except Exception as exc:
            LOG.warning("ThaiWater %s background refresh failed: %s", name, type(exc).__name__)
            snapshots[name] = {"stations": [], "stale": True, "refresh_error": type(exc).__name__}
    if not snapshots["waterlevel"].get("stations") and not snapshots["rainfall"].get("stations"):
        return {"persisted": False, "reason": "NO_STATION_SNAPSHOTS"}
    result = await asyncio.to_thread(persist_live_snapshots, snapshots["waterlevel"], snapshots["rainfall"])
    if not result.get("persisted"):
        LOG.warning("ThaiWater canonical observation persistence unavailable: %s", result.get("reason"))
    return result


async def background_refresh() -> None:
    while True:
        await refresh_once()
        await asyncio.sleep(600)
