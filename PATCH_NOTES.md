# Thailand Water — Implementation Patch Notes

This patch preserves the frozen hydrologic logic and UX direction while fixing operational readiness, topology traversal, and visible upstream-to-outlet flow.

## What changed

### Readiness / situation reporting
- Replaced overly global readiness behavior with per-location evidence handling.
- Added situation-report capability so the app can report what is known even when hazard/quantitative forecast is not yet eligible.
- Rain gauges may contribute catchment rainfall context without pretending to be hydraulically connected river gauges.
- Stage stations are classified using HydroRIVERS topology instead of same-catchment alone.
- Coastal readiness can use an available Navy tide source as forecast-boundary evidence without mislabeling it as observed sea level.

### River network / topology
- HydroRIVERS `NEXT_DOWN` is now the authoritative directional backbone for deterministic downstream traversal.
- Upstream traversal keeps multiple tributaries rather than selecting one arbitrary branch.
- DPM main/secondary waterways can be imported as named local reference geometry; they are explicitly `REFERENCE_ONLY` and do not invent flow direction.
- Nearest reach resolution prefers reaches in the containing catchment before pure distance.
- Route responses include GeoJSON geometry, reach counts, route length, truncation, and terminal information.

### Source-to-outlet flow
- Added `/v1/network/source-to-outlet`.
- Added real route drawing on the map for upstream, downstream, and combined source→outlet views.
- Added arrow rendering and a simple flow pulse animation for selected HydroRIVERS topology routes.

### Source / DB handling
- Added DPM hydrology source registration and import scripts.
- Added migrations for reference waterways and HydroRIVERS topology indexes.
- Database health now checks the actual migration set and reports missing migrations.
- Local startup runs idempotent migrations and attempts DPM hydrology bootstrap automatically.

### Frontend resilience
- Replaced all-or-nothing `Promise.all` location loading with partial-result handling.
- One failed API no longer erases readiness/context/risk results from successful APIs.

## Validation performed in the patch environment

Passed:

```text
25 tests passed + 8 regression subtests
python -m compileall -q app data db scripts tests
node --check web/assets/app.js
```

Full PostGIS integration tests could not run in the patch sandbox because `psycopg` was unavailable and that environment could not download packages. Run the normal local startup on the target machine to verify DB/API integration.

## Start / migrate / import

On Windows PowerShell from the project directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_local.ps1 -OpenBrowser
```

Startup now runs migrations and attempts DPM hydrology import when the reference-waterway table is empty.

Manual DPM import if needed:

```powershell
.\.venv\Scripts\python.exe -m scripts.import_dpm_hydrology
```

## Useful checks

```powershell
Invoke-RestMethod http://127.0.0.1:8899/v1/data-quality

Invoke-RestMethod "http://127.0.0.1:8899/v1/location/readiness?lat=13.5901&lon=100.1074"

Invoke-RestMethod "http://127.0.0.1:8899/v1/network/source-to-outlet?lat=13.5901&lon=100.1074"
```

## Important safety behavior retained

- `NOT_READY` never means safe.
- Missing sources do not become zero.
- DPM reference waterways do not get invented flow direction.
- Quantitative ETA/peak/depth remains gated by evidence and model eligibility.
