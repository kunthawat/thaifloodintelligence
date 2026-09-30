"""Generate the frozen, numbered SQL migrations from the supplied manifest.

This is a maintenance utility. The checked-in migrations are ordinary SQL and
do not need this script at runtime.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "thailand_flood_intelligence_implementation_data_manifest.md"
MIGRATIONS = ROOT / "db" / "migrations"


def block_after(lines: list[str], heading: str) -> list[str]:
    start = lines.index(heading) + 1
    while start < len(lines) and not lines[start].startswith("```"):
        start += 1
    if start == len(lines):
        raise ValueError(f"No code block follows {heading}")
    end = start + 1
    while end < len(lines) and not lines[end].startswith("```"):
        end += 1
    if end == len(lines):
        raise ValueError(f"Unclosed code block after {heading}")
    return lines[start + 1 : end]


def write(name: str, lines: list[str]) -> None:
    body = "\n".join(lines).strip() + "\n"
    (MIGRATIONS / name).write_text(
        "-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md\n"
        + body,
        encoding="utf-8",
    )


def main() -> None:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    MIGRATIONS.mkdir(parents=True, exist_ok=True)
    write("001_types.sql", block_after(lines, "# 5. SQL TYPES"))
    groups = {
        "010_sources.sql": ["## Sources"],
        "020_geography.sql": ["## Geography"],
        "030_network.sql": ["## Dynamic network"],
        "040_stations.sql": ["## Stations"],
        "050_observations.sql": ["## Observations"],
        "060_controls_boundaries.sql": ["## Controls / boundaries"],
        "070_bank_storage.sql": ["## Banks / storage"],
        "080_events.sql": ["## Events / waves"],
        "090_forecasts.sql": ["## Forecasts"],
        "100_warnings_impacts.sql": ["## Warnings / impacts"],
    }
    for filename, headings in groups.items():
        sections = [block_after(lines, heading) for heading in headings]
        write(filename, [line for section in sections for line in section])
    index_lines = block_after(lines, "# 7. REQUIRED INDEXES")
    write("110_indexes.sql", index_lines)


if __name__ == "__main__":
    main()
