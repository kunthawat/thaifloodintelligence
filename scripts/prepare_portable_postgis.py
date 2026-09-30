"""Install official Windows PostgreSQL and PostGIS ZIPs into local_runtime/pgsql."""

from __future__ import annotations

import argparse
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from app.settings import ROOT


def extract_selected(archive: Path, destination: Path, root_name: str) -> int:
    count = 0
    allowed = {"bin", "lib", "share", "gdal-data"}
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        bad_entry = bundle.testzip()
        if bad_entry:
            raise ValueError(f"ZIP CRC failed: {bad_entry}")
        for info in bundle.infolist():
            parts = PurePosixPath(info.filename).parts
            if len(parts) < 3 or parts[0] != root_name or parts[1] not in allowed:
                continue
            if any(part in {".", ".."} or ":" in part for part in parts):
                raise ValueError(f"Unsafe ZIP path: {info.filename}")
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                raise ValueError(f"ZIP symlink not allowed: {info.filename}")
            target = destination.joinpath(*parts[1:]).resolve()
            if destination not in target.parents:
                raise ValueError(f"ZIP path outside runtime: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            count += 1
    return count


def restore_postgres_dlls(postgres_zip: Path, postgis_zip: Path, destination: Path, postgis_root: str) -> int:
    """Keep PostgreSQL's own shared DLL versions where both bundles include one."""
    with zipfile.ZipFile(postgres_zip) as postgres, zipfile.ZipFile(postgis_zip) as postgis:
        postgres_names = {name.removeprefix("pgsql/") for name in postgres.namelist() if name.startswith("pgsql/bin/")}
        postgis_names = {name.removeprefix(postgis_root + "/") for name in postgis.namelist() if name.startswith(postgis_root + "/bin/")}
        collisions = sorted(name for name in postgres_names & postgis_names if name.casefold().endswith(".dll"))
        for relative in collisions:
            target = destination.joinpath(*PurePosixPath(relative).parts)
            with postgres.open("pgsql/" + relative) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return len(collisions)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-zip", type=Path, required=True)
    parser.add_argument("--postgis-zip", type=Path, required=True)
    args = parser.parse_args()
    destination = ROOT / "local_runtime" / "pgsql"
    destination.mkdir(parents=True, exist_ok=True)
    postgres_root = next(
        part.split("/", 1)[0]
        for part in zipfile.ZipFile(args.postgres_zip).namelist()
        if part.startswith("pgsql/bin/postgres.exe")
    )
    with zipfile.ZipFile(args.postgis_zip) as bundle:
        postgis_root = next(
            part.split("/", 1)[0]
            for part in bundle.namelist()
            if part.endswith("/share/extension/postgis.control")
        )
    postgres_files = extract_selected(args.postgres_zip, destination, postgres_root)
    postgis_files = extract_selected(args.postgis_zip, destination, postgis_root)
    restored_dlls = restore_postgres_dlls(args.postgres_zip, args.postgis_zip, destination, postgis_root)
    print(f"Installed {postgres_files} PostgreSQL and {postgis_files} PostGIS files into {destination}; preserved {restored_dlls} PostgreSQL DLLs")


if __name__ == "__main__":
    main()
