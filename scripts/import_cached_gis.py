"""Validate and import official GIS archives already downloaded under data/static."""

from __future__ import annotations

import argparse
import json

from app.settings import data_path
from data.connectors.static import StaticHydroConnector, _safe_extract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_id", choices=("hydrobasins", "hydrorivers", "hydrosheds"))
    args = parser.parse_args()
    root = data_path("STATIC_DATA_DIR", "data/static") / args.source_id
    archives = sorted(root.glob("*.zip"))
    if not archives:
        raise SystemExit(f"No official ZIP archive found under {root}")
    for archive in archives:
        extracted = archive.parent / archive.stem
        marker = extracted / ".extraction-complete"
        fingerprint = str(archive.stat().st_size)
        if not marker.is_file() or marker.read_text(encoding="ascii") != fingerprint:
            _safe_extract(archive, extracted)
            marker.write_text(fingerprint, encoding="ascii")
    result = StaticHydroConnector(args.source_id).import_dataset([str(path) for path in archives])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
