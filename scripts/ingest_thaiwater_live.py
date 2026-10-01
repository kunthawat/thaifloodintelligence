"""One-shot ThaiWater live observation ingest into the canonical database."""

from __future__ import annotations

import json

from app.services.live_observation_ingest import persist_live_snapshots
from app.services.rainfall_live import snapshot as rainfall_snapshot
from app.services.waterlevel_live import snapshot as waterlevel_snapshot


def main() -> None:
    result = persist_live_snapshots(waterlevel_snapshot(), rainfall_snapshot())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("persisted"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
