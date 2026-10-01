"""Refresh public station snapshots outside user-facing request paths."""

from __future__ import annotations

import asyncio
import logging

from app.services.rainfall_live import snapshot as rainfall_snapshot
from app.services.waterlevel_live import snapshot as waterlevel_snapshot

LOG = logging.getLogger(__name__)


async def refresh_once() -> None:
    for name, func in (("waterlevel", waterlevel_snapshot), ("rainfall", rainfall_snapshot)):
        try:
            await asyncio.to_thread(func)
        except Exception as exc:
            LOG.warning("ThaiWater %s background refresh failed: %s", name, type(exc).__name__)


async def background_refresh() -> None:
    while True:
        await refresh_once()
        await asyncio.sleep(600)
