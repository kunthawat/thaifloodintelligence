"""Discovery and validation for versioned HydroSHEDS vector/raster products."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.services.sources import SOURCES
from app.settings import data_path
from data.connectors.base import DiscoveryResult, anchors, fetch_https

STATIC_IDS = {"hydrosheds", "hydrobasins", "hydrorivers"}
_DEFINITION = {item.source_id: item for item in SOURCES}


class StaticHydroConnector:
    def __init__(self, source_id: str):
        self.source_id = source_id
        self.definition = _DEFINITION[source_id]

    async def discover_version(self) -> DiscoveryResult:
        page_url = self.definition.endpoint()
        if not page_url:
            return DiscoveryResult(self.source_id, "NOT_CONFIGURED", None)
        response = await fetch_https(page_url, timeout=8)
        if response.status != 200:
            return DiscoveryResult(self.source_id, "SOURCE_ERROR", page_url, details={"http_status": response.status})
        candidates = []
        for item in anchors(response.text):
            if not item["href"]:
                continue
            href = item["href"]
            path = urlparse(href).path.casefold()
            filename = Path(path).name
            if self.source_id == "hydrosheds":
                # The official Asia filenames use "as"; CON is the conditioned DEM.
                matched = re.fullmatch(r"as_(con|dir|acc)_3s\.zip", filename)
                if matched:
                    product = {"con": "dem", "dir": "dir", "acc": "acc"}[matched.group(1)]
                    candidates.append({"url": href, "label": filename, "source_page": response.url, "product": product})
            elif self.source_id == "hydrobasins":
                if "/standard/" in path and re.fullmatch(r"hybas_as_lev01-12_v[0-9a-z]+\.zip", filename):
                    candidates.append({"url": href, "label": filename, "source_page": response.url})
            elif self.source_id == "hydrorivers":
                if re.fullmatch(r"hydrorivers_v[0-9a-z]+_as_shp\.zip", filename):
                    candidates.append({"url": href, "label": filename, "source_page": response.url})
        required = 3 if self.source_id == "hydrosheds" else 1
        products_present = {item.get("product") for item in candidates}
        resolved = len(candidates) >= required and (self.source_id != "hydrosheds" or {"dem", "dir", "acc"}.issubset(products_present))
        status = "VALID" if resolved else "NOT_SUPPORTED"
        return DiscoveryResult(self.source_id, status, response.url, tuple(candidates), details={"candidate_count": len(candidates), "products_present": sorted(str(value) for value in products_present if value), "required_products": ["dem", "dir", "acc"] if self.source_id == "hydrosheds" else [self.source_id], "requires_manual_resolution": not resolved})

    async def healthcheck(self) -> dict[str, Any]:
        discovery = await self.discover_version()
        if discovery.status == "VALID":
            return {"status": "VALID", "message": None, "freshness": "STATIC_VERSIONED", "details": discovery.details}
        return {"status": "SOURCE_ERROR", "message": "Official product page is reachable, but requested Asia product download links were not resolved", "freshness": "UNKNOWN", "details": discovery.details}

    async def download(self, discovery: DiscoveryResult | None = None) -> list[str]:
        discovery = discovery or await self.discover_version()
        if discovery.status != "VALID":
            raise RuntimeError(f"{self.source_id} product links not resolved: {discovery.details}")
        directory = data_path("STATIC_DATA_DIR", "data/static") / self.source_id
        directory.mkdir(parents=True, exist_ok=True)
        output: list[str] = []
        for index, resource in enumerate(discovery.resources):
            url = resource["url"]
            if not urlparse(url).scheme == "https":
                from data.connectors.base import absolute_resource
                url = absolute_resource(discovery.endpoint or "", url)
            name = _filename(url, resource.get("label", ""), index)
            path = directory / name
            _download(url, path)
            if path.suffix.casefold() == ".zip":
                target = directory / path.stem
                marker = target / ".extraction-complete"
                fingerprint = str(path.stat().st_size)
                if not marker.is_file() or marker.read_text(encoding="ascii") != fingerprint:
                    _safe_extract(path, target)
                    marker.write_text(fingerprint, encoding="ascii")
            output.append(str(path))
        return output

    def validate(self, paths: list[str]) -> dict[str, Any]:
        files = [Path(path) for path in paths]
        root = data_path("STATIC_DATA_DIR", "data/static") / self.source_id
        files.extend(item for item in root.rglob("*") if item.is_file() and item not in files)
        if self.source_id == "hydrosheds":
            return _validate_rasters(files)
        return _validate_vectors(files, self.source_id)

    def import_dataset(self, paths: list[str]) -> dict[str, Any]:
        report = self.validate(paths)
        if not report.get("valid"):
            raise RuntimeError(f"{self.source_id} validation failed: {report.get('errors')}")
        if self.source_id == "hydrosheds":
            return _register_terrain_products(report)
        from scripts.import_hydro_vectors_pyogrio import import_hydrobasins, import_hydrorivers
        return import_hydrobasins(report) if self.source_id == "hydrobasins" else import_hydrorivers(report)


def _filename(url: str, label: str, index: int) -> str:
    path_name = Path(urlparse(url).path).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", path_name or label).strip("._")
    if not safe:
        safe = f"{index}.zip"
    return safe[:180]


def _download(url: str, destination: Path, max_bytes: int = 6_000_000_000) -> None:
    if destination.is_file() and destination.stat().st_size > 0:
        if destination.suffix.casefold() != ".zip":
            return
        try:
            with zipfile.ZipFile(destination) as archive:
                if archive.testzip() is None:
                    return
        except zipfile.BadZipFile:
            pass
    request = Request(url, headers={"User-Agent": "ThailandFloodIntelligence/0.2", "Accept": "application/zip,application/octet-stream,*/*"})
    temp = destination.with_suffix(destination.suffix + ".part")
    total = 0
    try:
        with urlopen(request, timeout=30) as response, temp.open("wb") as output:
            if not response.geturl().startswith("https://"):
                raise ValueError("download redirected away from HTTPS")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"dataset exceeded {max_bytes} byte safety limit")
                output.write(chunk)
        if total == 0:
            raise ValueError("download was empty")
        temp.replace(destination)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _safe_extract(archive: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        root = target_dir.resolve()
        for entry in bundle.infolist():
            target = (target_dir / entry.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"unsafe path in archive: {entry.filename}")
        bundle.extractall(target_dir)


def _validate_rasters(files: list[Path]) -> dict[str, Any]:
    raster_files = [path for path in files if path.suffix.casefold() in {".tif", ".tiff"}]
    if not raster_files:
        return {"valid": False, "errors": ["No extracted GeoTIFF files found"], "raster_files": []}
    try:
        import rasterio
    except ImportError:
        return {"valid": False, "errors": ["Install rasterio to validate GeoTIFF CRS, resolution and no-data values"], "raster_files": [str(path) for path in raster_files]}
    products: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    expected = {"dem": 32767, "dir": 255, "acc": 4294967295}
    for path in raster_files:
        key = _raster_product_key(path)
        if not key:
            continue
        try:
            with rasterio.open(path) as dataset:
                epsg = dataset.crs.to_epsg() if dataset.crs else None
                nodata = dataset.nodata
                if epsg != 4326:
                    errors.append(f"{path.name}: expected EPSG:4326, found {epsg}")
                if nodata is None or int(nodata) != expected[key]:
                    errors.append(f"{path.name}: expected no-data {expected[key]}, found {nodata}")
                target_resolution = 1 / 1200  # 3 arc-seconds in geographic degrees
                if any(abs(abs(value) - target_resolution) > 0.0000001 for value in dataset.res):
                    errors.append(f"{path.name}: expected 3 arc-second resolution, found {dataset.res}")
                if dataset.count < 1 or dataset.width < 1 or dataset.height < 1:
                    errors.append(f"{path.name}: raster dimensions are empty")
                products[key] = {"path": str(path), "crs": f"EPSG:{epsg}" if epsg else None, "nodata": nodata, "width": dataset.width, "height": dataset.height, "transform": list(dataset.transform)[:6]}
        except Exception as exc:
            errors.append(f"{path.name}: unreadable GeoTIFF ({type(exc).__name__})")
    for kind in ("dem", "dir", "acc"):
        if kind not in products:
            errors.append(f"required 3 arc-second Asia product missing: {kind}")
    dem_names = [Path(item["path"]).as_posix().casefold() for key, item in products.items() if key == "dem"]
    if not any("con" in name or "condition" in name for name in dem_names):
        errors.append("The DEM product could not be verified as the conditioned (CON) DEM")
    return {"valid": not errors, "errors": errors, "products": products, "raster_files": [str(path) for path in raster_files]}


def _raster_product_key(path: Path) -> str | None:
    name = path.as_posix().casefold()
    tokens = set(re.findall(r"[a-z0-9]+", name))
    if "conditioned" in name or "condem" in name or "con" in tokens:
        return "dem"
    if "dem" in tokens:
        return None
    if "dir" in tokens or "flowdirection" in name or "flow_direction" in name:
        return "dir"
    if "acc" in tokens or "aca" in tokens or "flowaccumulation" in name or "flow_accumulation" in name:
        return "acc"
    return None


def _validate_vectors(files: list[Path], source_id: str) -> dict[str, Any]:
    shapefiles = [path for path in files if path.suffix.casefold() == ".shp"]
    archives = [path for path in files if path.suffix.casefold() == ".zip"]
    errors: list[str] = []
    if archives:
        for path in archives:
            try:
                with zipfile.ZipFile(path) as bundle:
                    if bundle.testzip():
                        errors.append(f"{path.name}: CRC check failed")
            except zipfile.BadZipFile:
                errors.append(f"{path.name}: invalid ZIP")
    if not shapefiles:
        errors.append("No extracted shapefile found")
        return {"valid": False, "errors": errors, "vector_files": []}
    try:
        import pyogrio
    except ImportError:
        return {"valid": False, "errors": [*errors, "Install pyogrio to validate vector CRS, attributes and topology"], "vector_files": [str(path) for path in shapefiles]}
    required = {"hydrobasins": {"HYBAS_ID", "PFAF_ID"}, "hydrorivers": {"HYRIV_ID", "NEXT_DOWN", "MAIN_RIV", "LENGTH_KM", "DIST_DN_KM", "DIST_UP_KM", "CATCH_SKM", "UPLAND_SKM"}}[source_id]
    layer_info = []
    for path in shapefiles:
        try:
            info = pyogrio.read_info(path)
        except Exception as exc:
            errors.append(f"{path.name}: cannot open with GDAL ({type(exc).__name__})")
            continue
        fields = {str(name).upper() for name in info["fields"]}
        missing = required - fields
        if missing:
            errors.append(f"{path.name}: missing topology fields {sorted(missing)}")
        crs = info.get("crs")
        epsg = str(crs).split(":")[-1] if crs else None
        if epsg not in {"4326", "4269"}:
            errors.append(f"{path.name}: expected WGS84 vector CRS, found {epsg}")
        feature_count = int(info["features"])
        if feature_count <= 0:
            errors.append(f"{path.name}: vector layer is empty")
        layer_info.append({"path": str(path), "name": info["layer_name"], "fields": sorted(fields), "feature_count": feature_count, "epsg": epsg, "extent": [float(value) for value in info["total_bounds"]]})
    return {"valid": not errors, "errors": errors, "vector_files": layer_info, "required_fields": sorted(required)}


def _register_terrain_products(report: dict[str, Any]) -> dict[str, Any]:
    derivatives: dict[str, str] = {}
    gdal_translate = shutil.which("gdal_translate")
    derivative_root = data_path("RASTER_DATA_DIR", "data/rasters") / "derivatives"
    if gdal_translate:
        derivative_root.mkdir(parents=True, exist_ok=True)
        for kind, product in report["products"].items():
            original = Path(product["path"])
            target = derivative_root / f"hydrosheds-asia-3s-{kind}.tif"
            process = subprocess.run(
                [gdal_translate, "-of", "COG", "-co", "COMPRESS=DEFLATE", str(original), str(target)],
                capture_output=True, text=True, check=False,
            )
            if process.returncode == 0 and target.is_file() and target.stat().st_size > 0:
                derivatives[kind] = str(target)
            else:
                target.unlink(missing_ok=True)
    else:
        derivative_status = "gdal_translate unavailable; originals retained and COG derivatives were not built"
        derivatives = {}
    derivative_status = "built" if gdal_translate and len(derivatives) == len(report["products"]) else "partial" if derivatives else "not_built"

    from app.settings import configured_database_url
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("Install psycopg before registering terrain products") from exc
    url = configured_database_url()
    if not url:
        raise RuntimeError("Set DATABASE_URL or DATABASE_DSN before registering terrain products")
    inserted = 0
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            for kind, product in report["products"].items():
                original = Path(product["path"])
                inserted += _insert_terrain_product(cursor, Jsonb, kind, original, product, "ORIGINAL", "HydroSHEDS v1.1")
                if kind in derivatives:
                    derivative = Path(derivatives[kind])
                    derivative_info = dict(product)
                    derivative_info["source_original"] = str(original.resolve())
                    inserted += _insert_terrain_product(cursor, Jsonb, kind, derivative, derivative_info, "COG_DERIVATIVE", "HydroSHEDS v1.1")
    return {"registered": inserted, "products": list(report["products"]), "derivatives": derivatives, "derivative_status": derivative_status}


def _insert_terrain_product(cursor: Any, Jsonb: Any, kind: str, path: Path, info: dict[str, Any], product_variant: str, version: str) -> int:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    props = {"sha256": hasher.hexdigest(), "nodata": info["nodata"], "width": info["width"], "height": info["height"], "source_version": version, "original_preserved": True, "product_variant": product_variant}
    if info.get("source_original"):
        props["source_original"] = info["source_original"]
    cursor.execute(
        """INSERT INTO terrain_products
           (name,provider,product_type,resolution_m,horizontal_crs,quality_tier,uri,properties)
           VALUES (%s,'HydroSHEDS',%s,90,'EPSG:4326',%s,%s,%s)
           ON CONFLICT (name,uri) DO UPDATE SET properties=EXCLUDED.properties,quality_tier=EXCLUDED.quality_tier""",
        (f"Asia HydroSHEDS 3s {kind.upper()} {product_variant}", f"{kind.upper()}_{product_variant}", "T3_MOUNTAIN_SCREENING_T4_FLAT_COASTAL_DEPTH_RESTRICTED", str(path.resolve()), Jsonb(props)),
    )
    return 1
