# Thailand Flood Intelligence — Data Integration Recovery Plan v1

**Status:** IMPLEMENTATION PATCH — FROZEN LOGIC PRESERVED  
**Companion to:**  
- `thailand_flood_intelligence_master_implementation_spec.md`
- `thailand_flood_intelligence_implementation_data_manifest.md`

**Purpose:** Fix the current implementation state where `MAP_READY=true` but hazard readiness is globally blocked because several external sources are being treated as mandatory dependencies.

**Critical rule:** This document is an implementation correction only. It does **not** reopen hydrologic logic, product architecture, or UX/UI design.

---

# 0. Executive summary

The current implementation appears to behave approximately like:

```python
HAZARD_ONLY_READY = (
    tmd_qpe_ready
    and hii_ready
    and dwr_ready
    and warning_geometry_ready
    and gistda_ready
    and imerg_ready
)
```

This is **incorrect** relative to the frozen design.

The intended design is:

> **Readiness is evaluated per location, per hazard, and per forecast output.**

A missing optional source must degrade only the capability that depends on it.

Examples:

- TMD QPE unavailable → reduce spatial rainfall precision; do not disable river hazard.
- GISTDA key missing → confirmed-impact layer unavailable; do not disable hazard detection.
- IMERG auth missing → cross-border rainfall confidence decreases; do not disable Ban Phaeo/Ubon/etc.
- RID `inflow/outflow` unit unverified → do not use those fields in physics; still use verified storage/capacity fields.
- Navy tide is a forecast boundary, not an observation; still usable for coastal scenarios.
- DWR/HII timeout → use cached last-good/fallback and mark freshness/quality.
- Warning without geometry → geocode administrative scope using DPM administrative polygons.

Target platform state after this patch:

```text
MAP_READY = true
GLOBAL_HAZARD_STATUS = PARTIAL

Ban Phaeo:
  river = READY
  flash = PARTIAL
  coastal = READY

Mae Sai:
  flash = READY/PARTIAL
  river = PARTIAL

Ubon:
  river = READY/PARTIAL
```

Actual states remain evidence-dependent.

---

# 1. Replace one global hazard boolean

## 1.1 Required readiness levels

```text
READY
PARTIAL
NOT_READY
NOT_APPLICABLE
```

Required readiness scopes:

```text
global platform readiness
location readiness
hazard readiness
output readiness
source readiness
```

These are separate.

## 1.2 Required API concept

```json
{
  "platform": {
    "map_ready": true,
    "data_platform_ready": true,
    "global_hazard_status": "PARTIAL"
  },
  "location": {
    "lat": 13.5901,
    "lon": 100.1074,
    "status": "READY"
  },
  "hazards": {
    "river_overflow": "READY",
    "flash_flood": "PARTIAL",
    "coastal_tidal": "READY",
    "local_rain": "PARTIAL",
    "compound": "READY"
  }
}
```

## 1.3 Reference implementation

```python
class Readiness(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    NOT_READY = "NOT_READY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def evaluate_location_readiness(ctx):
    river = evaluate_river_readiness(ctx)
    flash = evaluate_flash_readiness(ctx)
    coastal = evaluate_coastal_readiness(ctx)
    local_rain = evaluate_local_rain_readiness(ctx)
    compound = evaluate_compound_readiness(
        river=river,
        flash=flash,
        coastal=coastal,
        local_rain=local_rain,
    )

    applicable = [river, flash, coastal, local_rain, compound]

    if any(x == Readiness.READY for x in applicable):
        overall = Readiness.READY
    elif any(x == Readiness.PARTIAL for x in applicable):
        overall = Readiness.PARTIAL
    else:
        overall = Readiness.NOT_READY

    return {
        "overall": overall,
        "hazards": {
            "river_overflow": river,
            "flash_flood": flash,
            "coastal_tidal": coastal,
            "local_rain": local_rain,
            "compound": compound,
        },
    }
```

---

# 2. River/canal hazard readiness

River hazard must not require TMD QPE, GISTDA, and IMERG simultaneously.

## 2.1 READY

River hazard can be `READY` if at least one valid evidence path exists:

```text
A. fresh connected stage/water-level observation
OR
B. scoped official river/canal flood warning
OR
C. confirmed inundation/flood impact
OR
D. calibrated routed upstream event/wave with sufficient observations
```

## 2.2 PARTIAL

Examples:

```text
connected H exists but is stale within recoverable state-estimation window
official warning exists but scope confidence is moderate
upstream event exists but local H unavailable
network topology known but control states uncertain
```

## 2.3 NOT_READY

Only when:

```text
no usable stage evidence
AND no scoped official warning
AND no confirmed impact
AND no connected upstream event evidence
```

---

# 3. Flash-flood readiness

Flash hazard must not require all of:

```text
TMD numeric QPE
DWR
HII
IMERG
GISTDA
```

at once.

## 3.1 READY — official/event path

```text
scoped DWR EWS warning
+
usable catchment/terrain
```

OR model path:

```text
recent sub-hour rainfall
+
catchment terrain
+
wetness/antecedent-rain estimate
```

Useful but not universally mandatory:

```text
upstream H
soil moisture
global rain
```

## 3.2 PARTIAL

Examples:

```text
DWR warning exists but rainfall detail missing
rainfall exists but wetness estimate weak
cross-border catchment and IMERG unavailable
terrain only T3/T4
```

## 3.3 NOT_READY

Only when there is no warning, no rainfall trigger evidence, and no usable upstream/catchment evidence.

---

# 4. Coastal/tidal readiness

## 4.1 READY

Requires:

```text
known downstream coastal/tidal boundary
AND (
    fresh observed downstream/sea stage
    OR official predicted tide
)
```

## 4.2 PARTIAL

Examples:

```text
Navy tide exists but no observed estuary stage
boundary propagation uncalibrated
datum uncertainty remains
```

## 4.3 NOT_READY

Only if no useful downstream boundary information exists.

---

# 5. Compound readiness

Compound risk is allowed if at least two relevant processes have usable evidence.

Example:

```text
river = READY
coastal = READY
local_rain = PARTIAL

=> compound = READY/PARTIAL
```

Do not require every hazard component.

---

# 6. Fix TMD QPE handling

## 6.1 Current problem

The official TMD discovery page may still advertise Nationwide QPE/QPE ASCII while a discovered target returns `404`.

This must not block hazard readiness.

## 6.2 Source role

Set:

```text
TMD_QPE_NUMERIC = DEGRADED_OPTIONAL
```

not:

```text
TMD_QPE_NUMERIC = REQUIRED
```

## 6.3 Discovery algorithm

```python
async def discover_tmd_qpe():
    page = await http_get(TMD_RADAR_DISCOVERY_URL)

    qpe_ascii_href = find_link_by_text(
        page,
        possible_texts=[
            "Nationwide QPE Ascii file",
            "QPE ASCII",
            "Nationwide QPE",
        ],
    )

    if not qpe_ascii_href:
        return SourceHealth(
            status="SOURCE_ERROR",
            message="QPE discovery link not found",
        )

    url = resolve_url(TMD_RADAR_DISCOVERY_URL, qpe_ascii_href)
    response = await http_get(url)

    if response.status_code == 404:
        return SourceHealth(
            status="SOURCE_ERROR",
            message="Current QPE target returned 404; rainfall fallback active",
        )

    validate_qpe_payload(response)
    return parse_qpe(response)
```

## 6.4 Rainfall fallback — Thailand

```text
1. TMD QPE/radar if usable
2. DWR 15-minute rainfall
3. HII/ThaiWater rainfall gauges
4. other verified national telemetry
5. IMERG/global precipitation
```

## 6.5 Rainfall fallback — cross-border

```text
1. available neighboring/local official source
2. IMERG/global precipitation
3. forecast precipitation ensemble
```

## 6.6 Mandatory interpretation

```text
QPE target 404
!= zero rain
!= no flash risk
!= global hazard NOT_READY
```

---

# 7. Fix HII/DWR parser handling

## 7.1 Current problem

Some HII/DWR sources return HTML tables, CSV, legacy HTML, different schema versions, timeout pages, or unexpected content types.

The connector must not assume JSON.

## 7.2 Universal response parser

```python
def parse_response(response):
    ctype = (response.headers.get("content-type") or "").lower()
    body = response.content

    if "application/json" in ctype or looks_like_json(body):
        return parse_json(body)

    if "text/csv" in ctype or looks_like_csv(body):
        return parse_csv(body)

    if "text/html" in ctype or looks_like_html(body):
        return parse_html(body)

    if looks_like_zip(body):
        return parse_zip(body)

    raise UnsupportedPayloadError(...)
```

## 7.3 Timeout policy

```text
connect timeout: 5–10 seconds
read timeout: 10–20 seconds
retry: maximum 2
backoff: exponential + jitter
```

After failure:

```text
source state = SOURCE_ERROR
use cached last-good if allowed by freshness policy
never block a user request waiting for a government source
```

## 7.4 Last-good cache

Required fields:

```text
last_success_at
last_observed_at
raw_hash
parsed_version
quality_state
freshness
```

Cached data is current only if freshness permits.

---

# 8. HII-specific repair

## 8.1 Archive role

HII archive = historical/calibration source.

Do not interpret archive availability as live-state readiness.

## 8.2 Current/public pages

Use only if:

```text
station identity verified
timestamp parsed
freshness acceptable
unit/datum valid
```

## 8.3 Legacy station ID verification

Do not hard-code ambiguous IDs.

R&D discovered conflicting candidates for MK03, therefore the connector must verify identity:

```python
def verify_legacy_station_id(candidate_id, expected_code, expected_name):
    page = fetch_legacy_station_page(candidate_id)
    returned_code, returned_name = parse_identity(page)

    if normalized(returned_code) == normalized(expected_code):
        return "VERIFIED"

    if strong_name_match(returned_name, expected_name):
        return "CANDIDATE_REQUIRES_REVIEW"

    return "CONFLICT"
```

No numeric provider mapping may enter the production graph until verified.

---

# 9. DWR-specific repair

DWR EWS pages are HTML-first sources.

## 9.1 Warning source

```text
https://ews.dwr.go.th/ews/warn_list.php
```

Store warnings as:

```text
observation_type = OFFICIAL_WARNING
```

Do not convert warning severity to water level/discharge.

## 9.2 Station series

```text
https://ews.dwr.go.th/ews/list_temp.php?link={station_code}
```

Potential values include:

```text
15-minute rainfall
accumulated rainfall
water level
soil moisture where supported
```

## 9.3 DWR timeouts

```text
SOURCE_ERROR
+
last-good cache if freshness permits
+
other hazards continue to evaluate
```

---

# 10. Fix official-warning spatial matching

## 10.1 Current problem

Warnings often contain text scope rather than geometry, for example:

```text
อ.บ้านแพ้ว จ.สมุทรสาคร
ต.บ้านแพ้ว
พื้นที่ริมคลองดำเนินสะดวก
```

Without geometry, the warning cannot be matched reliably to a user point.

## 10.2 Import DPM administrative boundaries

Use the DPM administrative FeatureServer family:

```text
https://gis-portal.disaster.go.th/arcgis/rest/services/MapDX/DPM_TH_Boundary/FeatureServer/
```

Import province, amphoe/district, and tambon/subdistrict layers.

Create:

```sql
CREATE TABLE admin_province (
  prov_code text PRIMARY KEY,
  prov_name_th text,
  geom geometry(MultiPolygon,4326) NOT NULL
);

CREATE TABLE admin_amphoe (
  amp_code text PRIMARY KEY,
  prov_code text,
  prov_name_th text,
  amp_name_th text,
  geom geometry(MultiPolygon,4326) NOT NULL
);

CREATE TABLE admin_tambon (
  tam_code text PRIMARY KEY,
  amp_code text,
  prov_code text,
  prov_name_th text,
  amp_name_th text,
  tam_name_th text,
  geom geometry(MultiPolygon,4326) NOT NULL
);
```

Create GIST indexes.

## 10.3 Warning schema extension

```sql
ALTER TABLE official_warnings
ADD COLUMN scope_method text,
ADD COLUMN scope_confidence double precision,
ADD COLUMN admin_level text,
ADD COLUMN admin_code text,
ADD COLUMN scope_text_normalized text;
```

## 10.4 Scope methods

```text
PROVIDER_GEOMETRY
ADMIN_TAMBON_MATCH
ADMIN_AMPHOE_MATCH
ADMIN_PROVINCE_MATCH
STATION_POINT
STATION_CATCHMENT
HYDROLOGIC_FEATURE_INTERSECTION
PROVINCE_APPROX
UNRESOLVED_TEXT
```

## 10.5 Thai name normalization

Normalize/remove prefixes:

```text
จ.
จังหวัด
อ.
อำเภอ
ต.
ตำบล
```

Also normalize whitespace and common punctuation.

## 10.6 Geocoding priority

```text
1. provider geometry
2. tambon exact match
3. amphoe exact match
4. province exact match
5. station/catchment mapping
6. hydrologic feature + admin intersection
7. unresolved text
```

## 10.7 Hydrologic feature intersection

For:

```text
พื้นที่ริมคลองดำเนินสะดวก อ.บ้านแพ้ว
```

derive a more useful scope:

```text
Ban Phaeo amphoe polygon
INTERSECT
buffer(Damnoen Saduak canal geometry)
```

Do not scope an entire province when a narrower hydrologic scope is available.

---

# 11. Fix RID usability classification

RID is partially usable, not globally unusable.

## 11.1 Safe verified fields

```text
capacity
storage
active_storage
dead_storage
volume
percent_storage
```

Use verified MCM/percentage semantics.

## 11.2 Unsafe fields until unit is verified

```text
inflow
outflow
```

Store them as raw context:

```text
semantic_status = UNVERIFIED
unit = null
physics_eligible = false
```

## 11.3 Readiness effect

Unverified RID inflow/outflow blocks only calculations that specifically require those terms.

It must not set hazard readiness to NOT_READY globally.

---

# 12. Fix Navy tide usability classification

Navy tide is a **forecast boundary**.

It is not an observed sea level, but it is still useful.

Use it for:

```text
coastal/tidal scenario
downstream-boundary forecast
gravity-drainage constraint scenario
```

Store:

```text
observation_type = FORECAST
datum = MSL when MSL edition is used
```

Optional observed-boundary hierarchy:

```text
verified fresh observed estuary/sea stage
→ Navy predicted tide
→ uncertain boundary ensemble
```

Any observed candidate must pass timestamp, identity, datum, spike, and range QC.

---

# 13. GISTDA is optional for hazard readiness

Role:

```text
confirmed flood extent
impact validation
historical flood frequency
reality check
```

Missing API key:

```text
source status = NOT_CONFIGURED
```

Effects:
- satellite impact layer unavailable;
- some impact confidence lower;
- river/flash/coastal hazard detection continues.

Do not make GISTDA a global readiness prerequisite.

---

# 14. IMERG is optional for most locations

Role:

```text
cross-border rainfall
broad antecedent rainfall
fallback spatial rainfall
```

Missing auth:

```text
NOT_CONFIGURED
```

Effects:
- Mae Sai/transboundary confidence decreases;
- Ban Phaeo/Ubon/etc. remain operational through other evidence paths.

Do not make IMERG a global prerequisite.

---

# 15. Source capability matrix

| Source | Role | Global hard dependency? |
|---|---|---:|
| HydroSHEDS/HydroBASINS/HydroRIVERS | static hydro context | yes for nationwide map/context |
| DPM admin boundaries | warning geocoding | strongly recommended |
| HII current H | river evidence | no |
| HII archive | calibration | no |
| DWR EWS | flash/warning | no |
| TMD QPE numeric | spatial rainfall detail | no |
| HII/DWR rain | rainfall fallback | no |
| RID storage | reservoir context | no |
| RID inflow/outflow | physical forcing if verified | no |
| Navy tide | coastal forecast boundary | no |
| observed estuary/sea H | coastal observed boundary | no |
| GISTDA | impact confirmation | no |
| IMERG | cross-border/fallback rain | no |
| LDD | soil/land use | no; improves runoff |

---

# 16. Global readiness becomes coverage-based

Instead of:

```json
{"HAZARD_ONLY_READY": false}
```

return:

```json
{
  "map_ready": true,
  "data_platform_ready": true,
  "global_hazard_status": "PARTIAL",
  "coverage": {
    "river": {"status": "PARTIAL"},
    "flash": {"status": "PARTIAL"},
    "coastal": {"status": "PARTIAL"}
  }
}
```

Do not fabricate coverage percentages until actual geographic coverage is computed.

---

# 17. Add location readiness endpoint

```text
GET /v1/location/readiness?lat=...&lon=...
```

Example:

```json
{
  "location": {
    "lat": 13.5901,
    "lon": 100.1074
  },
  "overall": "READY",
  "hazards": {
    "river_overflow": {
      "status": "READY",
      "reasons": [
        "SCOPED_OFFICIAL_WARNING",
        "CONNECTED_STAGE_EVIDENCE"
      ]
    },
    "flash_flood": {
      "status": "PARTIAL",
      "reasons": [
        "NO_NUMERIC_QPE",
        "TERRAIN_AVAILABLE"
      ]
    },
    "coastal_tidal": {
      "status": "READY",
      "reasons": [
        "NAVY_TIDE_AVAILABLE",
        "DOWNSTREAM_BOUNDARY_KNOWN"
      ]
    }
  }
}
```

---

# 18. Source health must not equal hazard readiness

Example:

```text
source health:
TMD_QPE = SOURCE_ERROR

hazard readiness:
river = READY
flash = PARTIAL
coastal = READY
```

One source error dictates a hazard result only when it is the only eligible evidence path.

---

# 19. Warning-to-point resolver

```python
def warning_applies_to_location(warning, point):
    if warning.geom:
        return point.within(warning.geom)

    if warning.admin_code:
        geom = load_admin_geom(warning.admin_level, warning.admin_code)
        return point.within(geom)

    if warning.scope_method == "HYDROLOGIC_FEATURE_INTERSECTION":
        return point.within(warning.derived_scope_geom)

    return None
```

`None` means unresolved, not `False`.

---

# 20. Cached last-good policy

Each connector classifies cached observations as:

```text
FRESH
STALE_CONTEXT_ONLY
REJECT_AS_CURRENT
```

Reference:

```python
def classify_freshness(age, warn_after, reject_after):
    if age <= warn_after:
        return "FRESH"
    if age <= reject_after:
        return "STALE_CONTEXT_ONLY"
    return "REJECT_AS_CURRENT"
```

Stale context may remain visible in Expert UI with timestamp.

---

# 21. Normalize hazard evidence

Create an internal evidence object:

```python
@dataclass
class HazardEvidence:
    hazard_type: str
    evidence_type: str
    location_or_geom: object
    observed_at: datetime
    source_id: str
    quality_state: str
    confidence: float | None
    freshness: str
    details: dict
```

Evidence types include:

```text
FRESH_STAGE
RISING_STAGE
OFFICIAL_WARNING
CONFIRMED_IMPACT
SUBHOUR_RAIN
ANTECEDENT_RAIN
UPSTREAM_WAVE
HIGH_TIDE_FORECAST
OBSERVED_DOWNSTREAM_STAGE
PUMP_DEGRADED
GATE_UNKNOWN
```

Readiness evaluates evidence sets, not raw source booleans.

---

# 22. Revised startup readiness

A valid startup can be:

```text
DATA_PLATFORM_READY = true
MAP_READY = true
GLOBAL_HAZARD_STATUS = PARTIAL
```

Do not require nationwide hazard READY before serving location hazard endpoints.

---

# 23. Required patch order

## Patch 1 — readiness refactor

Replace global boolean dependency with:
- source readiness;
- hazard readiness;
- location readiness;
- output eligibility.

## Patch 2 — multi-format connector dispatcher

Fix HII/DWR parser assumptions.

## Patch 3 — cache/backoff/last-good

Source timeouts must not block users.

## Patch 4 — DPM administrative boundary import

Province/amphoe/tambon polygons.

## Patch 5 — warning geocoder

Map warning text/admin scope to polygons.

## Patch 6 — TMD QPE degradation

Dynamic discovery/fallback; remove global hard dependency.

## Patch 7 — RID partial semantics

Use verified storage fields; lock inflow/outflow.

## Patch 8 — Navy tide classification

Enable as forecast boundary.

## Patch 9 — GISTDA/IMERG credential states

Use `NOT_CONFIGURED`, not global failure.

## Patch 10 — source health/readiness API

Expose why each hazard is READY/PARTIAL/NOT_READY.

---

# 24. Acceptance tests

## 24.1 TMD QPE down

Given:

```text
TMD QPE = 404
DWR warning = available
HydroSHEDS = available
```

Expected:

```text
flash readiness = READY or PARTIAL
global hazard status != NOT_READY solely due TMD
```

## 24.2 GISTDA key missing

Expected:

```text
gistda = NOT_CONFIGURED
confirmed flood layer unavailable
other readiness unchanged
```

## 24.3 IMERG auth missing — Ban Phaeo

Expected:

```text
river readiness still READY/PARTIAL
IMERG absence does not disable location
```

## 24.4 IMERG auth missing — Mae Sai

Expected:

```text
flash readiness may be PARTIAL
confidence lower for cross-border rain
not automatically NOT_READY if DWR evidence exists
```

## 24.5 DWR warning scoped to Ban Phaeo

Given:

```text
warning = "อ.บ้านแพ้ว จ.สมุทรสาคร"
user point inside Ban Phaeo
```

Expected:

```text
warning_applies = true
scope_method = ADMIN_AMPHOE_MATCH
```

## 24.6 HII timeout

Expected:

```text
source health = SOURCE_ERROR
cached last-good used only according to age
user API responds normally
other evidence evaluated
```

## 24.7 RID inflow unit unknown

Expected:

```text
RID storage usable
RID inflow/outflow raw-only
physics_eligible = false
no crash
```

## 24.8 Navy tide only

Expected:

```text
coastal readiness can be PARTIAL/READY
observation_type = FORECAST
never mislabeled as observed sea stage
```

---

# 25. Required public UI behavior

If hazard evidence is sufficient but quantitative hydraulics are not:

```text
🔴 ความเสี่ยงสูง

มีคำเตือนในพื้นที่
และพบแรงกดดันจากต้นน้ำ/ปลายน้ำ

ความสูงสูงสุด:
ยังประเมินไม่ได้อย่างน่าเชื่อถือ
```

Do **not** show:

```text
ยังประเมินความเสี่ยงไม่ได้
```

unless the hazard itself is actually `NOT_READY`.

---

# 26. Data-quality panel example

```text
HII water level       ⚠ DEGRADED
DWR EWS               ✓ AVAILABLE
TMD QPE               ✕ SOURCE ERROR
Navy tide             ✓ AVAILABLE
RID storage           ✓ AVAILABLE
RID inflow/outflow    ? SEMANTICS UNVERIFIED
GISTDA flood          ⚙ NOT CONFIGURED
IMERG                 ⚙ NOT CONFIGURED
HydroSHEDS            ✓ READY
Admin boundaries      ✓ READY

River hazard          READY
Flash hazard          PARTIAL
Coastal hazard        READY
Peak-height forecast  NOT ELIGIBLE
Point depth           NOT ELIGIBLE
```

This distinction is mandatory.

---

# 27. Missing-variable rule

When one variable is missing:

```text
missing variable
→ lower confidence/eligibility of dependent capability
```

Do not automatically escalate to:

```text
entire location hazard = NOT_READY
```

unless that variable is truly mandatory for the specific hazard/output.

---

# 28. Expected behavior after patch

Old failure pattern:

```text
one external source failed
→ entire hazard engine disabled
```

Required pattern:

```text
source failed
→ dependent capability degrades
→ alternative evidence path evaluated
→ only affected outputs become unavailable
```

Example Ban Phaeo:

```text
TMD QPE failed
GISTDA not configured
IMERG not configured
fresh H partially available
official warning spatially scoped
Navy tide available
hydrologic network ready

Result:
river hazard = READY/PARTIAL
coastal hazard = READY
compound hazard = READY/PARTIAL
peak height = NOT ELIGIBLE
point depth = NOT ELIGIBLE
```

This is the intended product behavior.

---

# 29. Regression locations after patch

Work must report readiness for all five archetypes individually.

## Ban Phaeo

Expected evidence paths:

```text
river/canal warning
H/Hbank where fresh/usable
controlled canal graph
Tha Chin/coastal boundary
Navy tide
```

TMD/GISTDA/IMERG failure cannot by itself disable this location.

## Mae Sai

Expected:

```text
DWR EWS
15-minute rainfall/H where available
transboundary catchment
terrain
optional IMERG
```

Without IMERG: confidence degradation, not automatic failure.

## Nan

Expected:

```text
headwater/rain evidence
river observations
wave handoff
terrain
```

## Ubon

Expected:

```text
river H/Q evidence
floodplain storage context
Mekong downstream boundary
```

No flash layer must not imply no flood.

## Hat Yai

Expected:

```text
rain/multiple inflows
U-Taphao water level
lake/sea boundary
multi-wave event
```

---

# 30. Logging requirements

Every readiness decision should be explainable.

Example structured log:

```json
{
  "location_id": "...",
  "hazard": "FLASH_FLOOD",
  "readiness": "PARTIAL",
  "positive_evidence": [
    "DWR_WARNING",
    "TERRAIN_READY"
  ],
  "missing": [
    "NUMERIC_QPE",
    "IMERG_NOT_CONFIGURED"
  ],
  "blocked_outputs": [
    "ARRIVAL_EXACT",
    "POINT_DEPTH"
  ]
}
```

This is required for debugging and Expert UI.

---

# 31. Metrics to add

Operational metrics:

```text
source_success_rate{source_id}
source_last_success_age_seconds{source_id}
source_timeout_count{source_id}
source_parse_error_count{source_id}
warning_geocode_success_rate
warning_scope_unresolved_count
hazard_readiness_count{hazard,status}
forecast_eligibility_count{output,eligible}
```

Do not rely only on logs.

---

# 32. Warning-geocoder QA

Create tests for Thai administrative forms:

```text
จ.สมุทรสาคร
จังหวัดสมุทรสาคร
อ.บ้านแพ้ว
อำเภอบ้านแพ้ว
ต.บ้านแพ้ว
ตำบลบ้านแพ้ว
```

They must normalize to canonical codes.

Ambiguous duplicate tambon names require province/amphoe context before matching.

Never resolve an ambiguous Thai place name to the first database row silently.

---

# 33. Parser QA

Store fixture snapshots for:

```text
DWR warn_list HTML
DWR list_temp HTML
HII warning table HTML
HII legacy daily HTML
RID JSON
Navy tide parsed table output
TMD discovery HTML
```

Parser tests must run offline from fixtures, so government site downtime does not prevent CI.

---

# 34. User-facing source outage semantics

Do not expose raw engineering errors such as:

```text
HTTP 404
parser failed
connection timeout
```

Public UI:

```text
ข้อมูลฝนเชิงพื้นที่บางแหล่งไม่พร้อมใช้งาน
ระบบกำลังใช้ข้อมูลสถานีภาคพื้นดินแทน
```

Expert UI can show:

```text
TMD_QPE: SOURCE_ERROR — discovered target returned HTTP 404
Fallback: DWR/HII gauge rainfall
```

---

# 35. Quantitative forecast remains gated

This recovery patch is specifically to restore hazard assessment.

It must **not** weaken quantitative eligibility rules.

Even after hazard becomes READY:

```text
peak_height may remain NOT ELIGIBLE
bankfull ETA may remain PARTIAL
point depth may remain NOT ELIGIBLE
```

That is expected and correct.

---

# 36. Definition of done for this recovery patch

The patch is complete when:

1. `MAP_READY=true` no longer implies a single global hazard boolean.
2. location/hazard readiness API exists.
3. TMD QPE 404 does not disable all hazards.
4. HII/DWR HTML parsers operate from fixtures and live sources where available.
5. timeout/cache behavior works.
6. DPM admin polygons are imported.
7. official warning text can be scoped to point for common province/amphoe/tambon cases.
8. RID verified fields remain usable while unverified fields stay physics-blocked.
9. Navy tide is accepted as forecast boundary.
10. GISTDA and IMERG without credentials report `NOT_CONFIGURED` only.
11. five regression locations each return their own readiness explanation.
12. unsupported quantitative outputs remain eligibility-gated.

---

# 37. Final implementation instruction

**Implement this recovery plan before declaring hazard assessment unavailable globally.**

Required final behavior:

```text
MAP_READY can coexist with GLOBAL_HAZARD_STATUS=PARTIAL.

Each location/hazard is evaluated independently.

Optional-source failure no longer disables unrelated capabilities.

Warnings can be spatially matched using administrative boundaries.

HII/DWR HTML/CSV/legacy payloads are handled robustly.

TMD QPE 404 triggers fallback, not zero rain.

RID verified fields remain usable while unsafe fields are blocked.

Navy tide remains usable as a forecast boundary.

GISTDA/IMERG missing credentials become NOT_CONFIGURED, not global failure.
```

If none of the five regression locations reaches `READY` or `PARTIAL` after these patches, Work must report **the exact failed evidence path for each location**, rather than returning one global readiness boolean.

---

**END — DATA INTEGRATION RECOVERY PLAN v1**
