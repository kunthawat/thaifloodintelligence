# Thailand Flood Intelligence — Master Implementation Specification

**Status:** FROZEN FOR IMPLEMENTATION  
**Purpose:** Single source of truth for code implementation.  
**Audience:** Work / engineering agents / developers.  
**Scope:** Nationwide Thailand flood intelligence with river flood, flash flood, local-rain flood, coastal/tidal flood, and compound-flood support.

---

# 0. WORK EXECUTION CONTRACT — CODE ONLY

This section is **non-negotiable**.

Work is responsible for **writing code that implements this specification**.

Work must **NOT**:
- redesign the product;
- change hydrologic logic;
- replace the model architecture;
- change data-source policy;
- change warning semantics;
- change the Forecast Eligibility rules;
- merge or simplify hazard types without explicit approval;
- redesign the UX/UI;
- introduce a dashboard-first UX;
- remove uncertainty/confidence handling;
- invent missing data;
- interpret `NO DATA` as `NO RISK`;
- use an unverified unit or datum in physical equations;
- change regression/acceptance behavior to make tests pass;
- create fake numeric precision where eligibility is false.

If implementation reveals a conflict, missing capability, unavailable endpoint, undocumented schema, licensing restriction, or technical blocker:

1. **Do not redesign.**
2. Implement the safest existing fallback defined in this document.
3. Mark the blocker clearly in code/reporting.
4. Surface the exact blocker to the user.
5. Wait for explicit approval before changing architecture, logic, or UX/UI.

When this document says `MUST`, `MUST NOT`, `FROZEN`, or `NON-NEGOTIABLE`, Work has no design discretion.

---

# 1. PRODUCT GOAL

For any latitude/longitude in Thailand, the product should answer as much as the available evidence reliably supports:

1. Will flooding affect this area?
2. What kind of flood threat is dominant?
3. When might first impact occur?
4. When might nearby water reach bankfull / containment level?
5. How high might peak water be above the relevant bank/containment level?
6. When might peak occur?
7. How long might water remain above bank?
8. Is the selected point likely to be reached by floodwater?
9. If technically supportable, what depth range might occur at the point?
10. Where is the water coming from?
11. Where will it go / can it drain fast enough?
12. Why does the system think this?
13. How confident is each individual answer?

The system must be useful even when it cannot safely answer all 13 questions.

The product is not merely a water-level dashboard. It is a **hydrologic event and water-flow intelligence system**.

---

# 2. CORE UX PRINCIPLE

> **Public UI answers questions, not datasets.**

A normal user should understand the situation in approximately **5–10 seconds**.

Default Public UI must not require knowledge of:
- m MSL / ม.รทก.;
- m³/s;
- rating curves;
- station IDs;
- P10/P50/P90 terminology;
- pump scenarios;
- model versions;
- graph confidence.

Those belong in **Expert Mode**.

---

# 3. FROZEN HAZARD TYPES

```text
RIVER_OVERFLOW
FLASH_FLOOD
LOCAL_RAIN
COASTAL_TIDAL
COMPOUND
```

`COMPOUND` means meaningful interaction between multiple processes. It is not simply `max(other risks)`.

---

# 4. CORE HYDROLOGIC ARCHITECTURE — FROZEN

```text
                 HYDROLOGIC EVENT MANAGER
               ┌─────────────────────────┐
               │ Event / Wave / Pulse    │
               │ origin / ETA / status   │
               └────────────┬────────────┘
                            │
                     DATA QUALITY
                            │
                            ▼
                   STATE ESTIMATOR
                            │
           ┌────────────────┼─────────────────┐
           ▼                ▼                 ▼
       Catchment         Current H/Q     Control State
       wetness              state        gate/pump/etc.
           │                │                 │
           ▼                │                 │
      RUNOFF PULSES         │                 │
           └────────────────┼─────────────────┘
                            ▼
                 DYNAMIC HYDRAULIC GRAPH
                            │
           ┌────────────────┼────────────────┐
           ▼                ▼                ▼
       Channel          Floodplain        Control
       Routing           Storage          Structures
           │                │                │
           └────────────────┼────────────────┘
                            ▼
                  DOWNSTREAM BOUNDARY
             river / sea / lake / reservoir
                            │
                            ▼
                   EFFECTIVE Qout(t)
                            │
                            ▼
                     MASS BALANCE
                            │
                            ▼
                       STORAGE S(t)
                            │
                            ▼
                       STAGE H(t)
                            │
                            ▼
                 BANK / CONTAINMENT MODEL
                            │
                            ▼
                     OVERFLOW Q(t)
                            │
                            ▼
               TERRAIN + FLOODPLAIN ROUTING
                            │
                            ▼
                   LOCATION EXPOSURE
                            │
                            ▼
                    DATA ASSIMILATION
                            ↺
```

This architecture is frozen.

---

# 5. EVENT-DRIVEN MODEL

## 5.1 Hydrologic event

Water is tracked as identifiable hydrologic events and waves.

A single event may change hazard form:

```text
mountain rainfall
→ flash flood / rapid runoff
→ tributary routing
→ main-river wave
→ river overflow
→ floodplain filling
→ recession
```

## 5.2 Event state

```text
GENERATING
HEADWATER_ROUTING
TRIBUTARY_ROUTING
MAIN_RIVER_ROUTING
FLOODPLAIN_FILLING
RECESSION
ENDED
```

## 5.3 Event termination

An event must NOT be considered ended merely because local water level is falling.

End only when:
- all material runoff pulses have routed;
- no material upstream wave remains;
- forecast rainfall is not creating another linked wave;
- storage/floodplain recession is established.

## 5.4 Multi-wave

```text
EVENT
 ├── Wave 1: passed
 ├── Wave 2: in transit
 └── Wave 3: forecast-rain generated
```

UI must support:
> ระดับน้ำกำลังลดลงชั่วคราว แต่ยังมีมวลน้ำอีกระลอกจากต้นน้ำ

---

# 6. CATCHMENT / FLASH-FLOOD ENGINE

## 6.1 Catchments can cross national borders

Hydrological boundaries override national boundaries. Do not clip catchments at Thailand's border.

## 6.2 Static catchment attributes

```text
catchment_id
parent_catchment_id
area
mean_elevation
relief
mean_slope
max_slope
flow_length
time_of_concentration
drainage_density
flow_accumulation_metrics
soil_attributes
land_use_attributes
forest_cover
flash_flood_susceptibility
terrain_source
terrain_quality_tier
```

## 6.3 Dynamic catchment state

```text
antecedent_rain
soil_moisture
wetness_state
current_rain
forecast_rain
headwater_water_level
runoff_state
```

## 6.4 Wetness

```text
Wetness(t) =
f(observed soil moisture,
  antecedent rainfall,
  baseflow / upstream H,
  soil,
  land cover)
```

Fallback:
```text
DWR soil measurement
↓
satellite/GISTDA soil moisture where suitable
↓
Antecedent Precipitation Index estimate
```

## 6.5 Effective rainfall

```text
Pe(t) = P(t) - Loss(t)
```

Loss depends on soil, land use, slope, saturation/wetness.

## 6.6 Runoff pulses

```text
Rain
↓
Effective Rain
↓
Runoff Volume
↓
Travel Time
↓
Q(t)
```

At junctions:

```text
Q_junction(t) = Σ Q_i(t - T_i)
```

## 6.7 Flash outputs

When eligible:
```text
probability
arrival window
peak-risk window
duration
severity
```

Do not implement `Rain > threshold => flood` as the whole model.

---

# 7. RIVER / CHANNEL ROUTING

## Routing tiers

### R1 — Hydraulic/high-data
Q/H + geometry + boundaries + controls.

### R2 — Calibrated transfer
Paired H/Q history, event calibration, distributed lag, empirical attenuation.

### R3 — Stage propagation
Mostly H available.

### R4 — Trend/probabilistic hazard
Sparse data. May output risk/trend, not precise peak.

Travel time is a distribution:

```text
τ = f(H, Q, dH/dt, event class)
```

Do not store one universal travel time.

---

# 8. DYNAMIC WATER GRAPH

## Node types

```text
SOURCE
CATCHMENT
SUBCATCHMENT
HEADWATER
GAUGE
JUNCTION
CONFLUENCE
RESERVOIR
DIVERSION
GATE
PUMP
CANAL_CONNECTION
TIDE_BOUNDARY
OUTLET
FLOODPLAIN_STORAGE
```

## Edge types

```text
RIVER_REACH
CREEK
CANAL
CONTROLLED_CANAL
DIVERSION
GATE_PATH
PUMP_PATH
FLOODPLAIN_CONNECTION
ESTUARY
```

## Direction

```text
FORWARD
REVERSE
BIDIRECTIONAL
CONTROLLED
DYNAMIC
```

Effective direction may depend on upstream/downstream head, gate state, pump state, tide/boundary.

Controlled canals must not be hard-coded one-way.

---

# 9. CONTROL STRUCTURES

## Design capacity != effective capacity

```text
Q_effective(t)
=
Q_design
× Availability(t)
× HeadFactor(t)
× BlockageFactor(t)
× OperationFactor(t)
```

Required fields:

```text
capacity_design
capacity_effective
capacity_estimation_method
availability
head_factor
blockage_factor
operation_factor
confidence
observed_at
```

Gate fields when available:

```text
upstream_H
downstream_H
gate_count
gate_opening
gate_width
Q_observed
Q_estimated
operation_state
timestamp
```

Unknown pump state must not default to 0% or 100%.

Use conditional priors based on last state, age, maintenance, power, historical reliability, and event state.

---

# 10. DOWNSTREAM BOUNDARY

Supported types:

```text
SEA
TIDAL_RIVER
RIVER
LAKE
RESERVOIR
CONTROLLED_CANAL
UNKNOWN
```

Examples:
- Ban Phaeo: Damnoen → Tha Chin → tidal river → Gulf
- Ubon: Mun → Mekong
- Hat Yai: U-Taphao → Songkhla Lake → Gulf

---

# 11. TIDE / TIDAL RIVER PROPAGATION

Keep separate:

```text
astronomical_tide
observed_sea_level
surge_residual
```

If only predicted tide is available, uncertainty rises.

Do NOT directly use sea tide as inland gate downstream H.

Use:

```text
sea tide(t)
↓
estuary / tidal-river propagation
↓
river stage near gate
↓
head difference
↓
Qout
```

---

# 12. MASS BALANCE / STORAGE

```text
dS/dt = Qin - Qout
```

Conceptually:

```text
Qin_total =
river inflow
+ catchment runoff
+ local rainfall contribution
+ connected inflows
```

```text
Qout_effective =
channel outflow
+ gravity drainage
+ pumps
+ controlled gates
+ validated discharge paths
```

## Storage-stage rule

Mass balance does NOT directly give dH/dt.

Need:

```text
S = f(H)
```

Acceptable:
```text
SURVEYED_GEOMETRY
STAGE_STORAGE_CURVE
CROSS_SECTION_MODEL
CALIBRATED_EMPIRICAL_RELATION
VALIDATED_TRANSFER_MODEL
```

If absent:
```text
peak_height_eligible = false
```

---

# 13. FLOODPLAIN STORAGE / HYSTERESIS

Floodplain state:

```text
DRY
FILLING
CONNECTED
DRAINING
ISOLATED_PONDING
```

Before overflow:
```text
S = S_channel(H)
```

After connection:
```text
S = S_channel(H) + S_floodplain(H)
```

Exposure must use:
```text
current H
floodplain storage state
terrain connectivity
previous inundation
barriers
```

Same H during rising/falling limbs may produce different extents.

---

# 14. BANK / CONTAINMENT MODEL

Bank references are versioned and spatially scoped.

```text
bank_reference_id
reach_id
station_id
elevation
datum
reference_type
valid_from
valid_to
source
source_published_at
left_bank_elevation
right_bank_elevation
representative_geometry
spatial_extent
confidence
```

Reference types:

```text
SURVEYED_BANK
OFFICIAL_STATION_BANK
LEVEE_CREST
OPERATIONAL_CRITICAL_LEVEL
HISTORICAL_BANKFULL
DEM_ESTIMATE
```

`OPERATIONAL_CRITICAL_LEVEL` != physical bank by default.

A station bank threshold must not automatically apply to an entire reach.

---

# 15. TERRAIN / LOCATION EXPOSURE

## Terrain tiers

### T1
LiDAR/survey/high-res validated.
Eligible for exposure + point depth.

### T2
Local DEM ~5–30 m.
Exposure + conditional depth after validation.

### T3
~30–90 m.
Exposure probability; no precise depth by default.

### T4
HydroSHEDS ~90 m in flat floodplain/coastal terrain.
Screening only.

Do not use naive bathtub flooding.

Consider:
```text
hydraulic connectivity
HAND / relative drainage height
flow path
barriers / levees
distance from overflow source
floodplain storage
historical inundation
terrain quality
```

River +40 cm above bank does not mean point depth = 40 cm.

---

# 16. SOURCE POLICY

## HII / ThaiWater
Use for H/Q observations, historical calibration/hindcast, rainfall history where useful, station metadata, and explicit bank/threshold references.

Historical H archive can include ~10-minute stage records in m MSL. Missing sentinels such as `-999`, `999999`, `9999`, `-` become `MISSING`.

Historical archive must never masquerade as live data.

## DWR EWS
Tier-1 for flash flood:
- 15-minute rain;
- 12/24/48 h accumulated rain;
- water level;
- soil moisture where available;
- warnings/history;
- station metadata.

Measurements and official warnings remain distinct types.

## TMD
Primary Thailand spatial-rain source when available:
- radar;
- QPE;
- QPE ASCII.
Normalize timestamps to Asia/Bangkok.

## Global precipitation
Required for cross-border gaps.
Use products such as GPM/IMERG or equivalent.
Treat as cross-border/broader fallback, not necessarily the fastest local flash trigger.

## RID reservoir
Use reservoir state/history.
If inflow/outflow units/semantics are not verified:
```text
semantics_status = UNVERIFIED
```
and exclude from physical mass balance.

## Pumps/gates
Use best available registry/telemetry.
Static location/count/capacity is useful.
Missing realtime state expands uncertainty.

## Navy tide
Use official predicted tide; normalize datum.
Predicted tide != observed sea level.

## HydroSHEDS / HydroBASINS / HydroRIVERS
Nationwide hydrologic skeleton/fallback:
DEM, conditioned DEM, flow direction, accumulation, river network, basin hierarchy.

HydroRIVERS does not replace artificial canal data.

## Artificial canals
Collect as much verified data as feasible.
Incomplete network is acceptable with `network_confidence`.
Do not invent canals.

## LDD
Use for land use/soil where appropriate.

## GISTDA
Use for confirmed/recent flood extent, flood frequency, impact validation, historical susceptibility, and suitable soil-moisture products if available.
No flood polygon != no flood.

---

# 17. DATA SEMANTICS / QUALITY

Source registry:

```text
source_id
provider
dataset
endpoint_type
variables
native_unit
native_datum
native_timezone
aggregation_interval
semantics_status
license
commercial_use_status
expected_update_pattern
freshness_warn_after
freshness_reject_after
priority
fallback_group
auth_required
parser_version
schema_valid_from
schema_valid_to
```

Semantic state:

```text
VERIFIED
PARTIAL
UNVERIFIED
```

Observation state:

```text
VALID
VALID_ZERO
MISSING
STALE
SUSPECT
NOT_SUPPORTED
SOURCE_ERROR
ESTIMATED
```

Mandatory:

```text
NO DATA != ZERO
NO DATA != NORMAL
NO DATA != NO RISK
```

Quality pipeline:
```text
timestamp check
range check
spike check
neighbour check where possible
freshness
unit validation
datum validation
semantic validation
```

---

# 18. STATE ESTIMATION

Current state may combine:
- fresh H/Q;
- recent observations with age penalty;
- neighbor stations;
- upstream/downstream signals;
- confirmed impacts;
- tide/boundary;
- rainfall;
- historical dynamics.

Stale H must never silently become current H.

---

# 19. DATA ASSIMILATION

```text
forecast
↓
actual
↓
residual
↓
state correction
↓
wave amplitude / ETA correction
↓
uncertainty update
↓
rerun forecast
```

Forecasting is not open-loop.

---

# 20. ENSEMBLE / UNCERTAINTY

End-to-end:

```text
rain ensemble
→ runoff ensemble
→ wave ensemble
→ control-state ensemble
→ downstream-boundary ensemble
→ storage/H ensemble
→ exposure ensemble
```

Do not take a deterministic rainfall forecast and append arbitrary ±cm at the end.

Variables can be dependent. For example high tide lowers gravity drainage and increases pump dependence.

---

# 21. OFFICIAL WARNINGS

Official warning is independent evidence, not hydraulic forcing.

Allowed:
- display prominently;
- set minimum public alert visibility;
- increase urgency;
- discrepancy detection.

Forbidden:
```text
official warning red
→ arbitrary +H in model
```

If model and authority disagree:
- retain official warning;
- flag discrepancy;
- lower model confidence;
- generate engineering review signal.

---

# 22. FORECAST ELIGIBILITY — MANDATORY

Independent flags:

```text
occurrence_eligible
arrival_eligible
bankfull_eta_eligible
peak_height_eligible
peak_time_eligible
duration_eligible
location_exposure_eligible
point_depth_eligible
```

If false:

```text
value = null
eligible = false
reason = MACHINE_READABLE_REASON
```

Possible reasons:

```text
STALE_CURRENT_STAGE
NO_VALID_STAGE_STORAGE_MODEL
BANK_REFERENCE_UNAVAILABLE
BANK_REFERENCE_OUT_OF_SCOPE
CONTROL_STATE_TOO_UNCERTAIN
DOWNSTREAM_BOUNDARY_UNCERTAIN
TERRAIN_RESOLUTION_INSUFFICIENT
POINT_CONNECTIVITY_UNCERTAIN
SOURCE_SEMANTICS_UNVERIFIED
INSUFFICIENT_CALIBRATION
```

---

# 23. CONFIDENCE

Separate:

```text
occurrence
arrival
bankfull
peak_height
duration
location_exposure
point_depth
```

Inputs may include freshness, source quality, network confidence, calibration, ensemble spread, terrain quality, control uncertainty, boundary uncertainty.

---

# 24. FORECAST HORIZONS

Flash:
```text
NOW +30m +1h +2h +3h +6h
```

Short river/canal:
```text
NOW +3h +6h +12h +24h +48h
```

Large river/floodplain:
```text
NOW +12h +1d +2d +3d +5d +7d
```

Backend supplies recommended timeline.

---

# 25. FORECAST OUTPUT CONTRACT

Support:

```text
will_flood / probability
dominant_hazard
first_impact
time_to_bankfull
peak_above_bank
time_to_peak
duration_above_bank
location_exposure
point_depth when eligible
active_waves
risk_drivers
risk_reducers
uncertainties
official_warning
confidence by output
```

Example:

```json
{
  "generated_at": "...",
  "hazard": "COMPOUND",
  "overall_probability": 0.82,
  "first_impact": {
    "eligible": true,
    "p50_hours": 8,
    "range_hours": [5, 15]
  },
  "bankfull": {
    "eligible": true,
    "range_hours": [10, 20]
  },
  "peak_above_bank_m": {
    "eligible": false,
    "value": null,
    "reason": "NO_VALID_STAGE_STORAGE_MODEL"
  },
  "confidence": {
    "occurrence": "HIGH",
    "arrival": "MEDIUM",
    "peak_height": "UNAVAILABLE"
  },
  "active_waves": 2,
  "official_warning": true
}
```

Numbers are examples only.

---

# 26. DATABASE / STORAGE

Recommended:
```text
PostgreSQL
PostGIS
time-series partition/hypertable strategy
object storage for large grids/rasters
```

Core tables:

```text
source_registry
source_health
source_schema_versions

observations
observation_quality

basins
catchments
subcatchments
terrain_products

network_nodes
network_edges
edge_versions

stations
station_source_map

gates
pumps
control_state

reservoirs
reservoir_state

downstream_boundaries
boundary_state

bank_references
containment_segments

storage_nodes
stage_storage_curves
floodplain_state

hydrologic_events
event_waves
runoff_pulses

forecast_runs
forecast_members
forecast_outputs

official_warnings

flood_extents
location_exposure

model_versions
calibration_events
hindcast_metrics
```

---

# 27. CANONICAL OBSERVATION CONTRACT

```text
entity_id
variable
value
unit
datum
observed_at
received_at
source_id
source_record_id
quality_state
quality_score
observation_type
```

Types:
```text
OBSERVED
DERIVED
FORECAST
ESTIMATED
CONFIRMED_IMPACT
OFFICIAL_WARNING
```

---

# 28. INGESTION / CACHE

Frontend must not query slow government sites directly.

Suggested:
- H/Q live: 5–10 min where appropriate;
- DWR EWS: frequent poll + dedupe;
- TMD: ingest on new product timestamp;
- RID reservoir: roughly hourly unless source dictates;
- Tide: pre-ingest tables + interpolation;
- GISTDA: lower-frequency impact refresh;
- global satellite rain: native cadence/latency;
- historical HII: batch/archive.

Failure handling:
```text
cache
fallback provider
retry
exponential backoff
source health
```

---

# 29. CORE API — FROZEN

```text
GET /v1/location/context
GET /v1/location/risk
GET /v1/location/forecast
GET /v1/location/forecast/curve
GET /v1/location/explanation

GET /v1/network/upstream
GET /v1/network/downstream
GET /v1/network/waves

GET /v1/events/{id}
GET /v1/stations/{id}

GET /v1/official-warnings
GET /v1/data-quality

GET /v1/layers/{layer}
```

---

# 30. UX/UI V2 — FROZEN

## Main philosophy

Full-screen map first. Not a dashboard.

Desktop:

```text
┌────────────────────────────────────────────────────────────┐
│ THAI FLOOD       [ ค้นหาสถานที่... ]       Layers   ⚙    │
├──────────────────────────────────────┬─────────────────────┤
│                                      │ 📍 Selected place   │
│                                      │                     │
│             FULL MAP                 │ 🔴 Risk headline    │
│                                      │                     │
│   animated waterways / waves         │ Expected impact     │
│                                      │ window              │
│                📍                    │                     │
│                                      │ Main hazard         │
│                                      │                     │
│                                      │ [Why?] [Details]    │
├──────────────────────────────────────┴─────────────────────┤
│ adaptive hazard timeline                                   │
└────────────────────────────────────────────────────────────┘
```

First screen answers:
1. เสี่ยงไหม?
2. เมื่อไร?
3. ภัยหลักคืออะไร?
4. เชื่อได้แค่ไหน?

---

# 31. ADAPTIVE LOCATION CARD

Quantitative:
```text
🔴 มีแนวโน้มล้นตลิ่ง

เริ่มกระทบ
8–14 ชั่วโมง

สูงสุด
20–40 ซม. เหนือตลิ่ง

ช่วงสูงสุด
พรุ่งนี้ 18:00–02:00
```

Partial:
```text
🔴 มีแนวโน้มเกิดน้ำท่วม

เริ่มกระทบ
8–18 ชั่วโมง

ระดับสูงสุด
ยังประเมินไม่ได้อย่างน่าเชื่อถือ

เหตุผล:
ข้อมูลประตูระบายน้ำไม่ครบ
```

Hazard only:
```text
🔴 ความเสี่ยงเพิ่มสูง

พบมวลน้ำต้นทางกำลังเคลื่อนลงมา

เวลาและความสูง:
ข้อมูลยังไม่เพียงพอ
```

Do not use unexplained `"—"` placeholders.

---

# 32. OFFICIAL WARNING UI

Separate from model:

```text
┌────────────────────────────────┐
│ ⚠️ คำเตือนจากหน่วยงานทางการ   │
│ ปภ.: เฝ้าระวังน้ำล้นตลิ่ง      │
└────────────────────────────────┘

การประเมินของระบบ
🔴 ความเสี่ยงสูง
```

---

# 33. HAZARD BREAKDOWN

Default:
```text
ภัยหลัก
🌊 คลอง/แม่น้ำล้น     สูงมาก

ปัจจัยเสริม
🌊 น้ำทะเลหนุน
🌧 ฝนในพื้นที่
```

Full list behind interaction:
```text
River overflow
Flash flood
Local rainfall
Coastal/tidal
Compound
```

---

# 34. SIGNATURE UX — “น้ำมาจากไหน?”

On activation:
- fade unrelated features;
- highlight influencing upstream graph;
- animate direction;
- show active waves.

Example:
```text
Mae Klong Dam
↓
Wave A
↓
Bang Nok Khwaek
↓
Damnoen Canal
↓
📍
```

Wave states may show:
```text
Wave A: กำลังผ่านพื้นที่
Wave B: ต้นน้ำ, ETA 6–12 ชม.
```

---

# 35. SIGNATURE UX — “น้ำจะไปไหน?”

Show downstream route and constraints.

Public wording example:
```text
⚠️ การระบายช่วงเย็นอาจลดลง
เนื่องจากระดับน้ำปลายน้ำสูงขึ้น
```

Expert can show gate opening, pump state, downstream H, Qout, tide.

---

# 36. MAP ZOOM

Country:
- events;
- catchment/subbasin risk;
- aggregated warning areas;
- no station-pin overload.

Basin/province:
- rivers;
- waves;
- dams;
- major gauges;
- flood extent.

Community:
- local waterways;
- pumps/gates;
- barriers;
- selected point;
- local exposure/floodplain.

---

# 37. LAYERS

Default:
```text
Flood risk
Water flow
```

Quick:
```text
Rain/radar
Official warnings
Flood extent
```

Advanced:
```text
Gauges
Reservoirs
Pumps/gates
Terrain
HAND
Historical flood
Network confidence
```

---

# 38. TIMELINE UX

Adaptive by hazard:
- flash: minutes-hours;
- canal/river: hours-days;
- large river/floodplain: days-week.

Use backend `recommended_timeline`.

---

# 39. COLOR / ACCESSIBILITY

Color never stands alone.

```text
✓ ปกติ
! เฝ้าระวัง
▲ เสี่ยงสูง
⚠ อันตราย
? ข้อมูลไม่พอ
```

No-data state must be visually distinct from safe state.

---

# 40. MOBILE

Mobile is first-class.

Use:
- full map;
- draggable bottom sheet;
- compact 4-answer summary;
- simple “น้ำมาจากไหน?” action.

---

# 41. EXPERT MODE

May expose:
```text
Current H/Q
Hbank/containment reference
datum
dH/dt
active waves
Qin/Qout
control states
P10/P50/P90
model version
forecast tier
source timestamps
semantic states
network confidence
terrain tier
eligibility reasons
```

---

# 42. DATA LIMITATION STATE

Mandatory behavior when data is incomplete:

```text
🔴 ความเสี่ยงสูงมาก

ระดับน้ำ:
มีแนวโน้มเพิ่มขึ้น

ความสูงสูงสุด:
ยังประเมินไม่ได้อย่างน่าเชื่อถือ

เหตุผล:
ไม่มีข้อมูลการแบ่งน้ำเข้าคลองแบบ realtime
และไม่ทราบสถานะเครื่องสูบน้ำบางจุด

[ดูข้อมูลที่ขาด]
```

---

# 43. ALERT MODEL

Keep separate:
```text
MODEL_ALERT
OFFICIAL_ALERT
```

Official alert may set minimum visible public severity.

If official high but model low:
- retain official warning;
- flag discrepancy;
- reduce model confidence;
- generate engineering review.

---

# 44. REGRESSION SUITE — FROZEN

## Ban Phaeo
Tests:
- controlled canal;
- possible bidirectional flow;
- pumps/gates;
- tide;
- compound flooding;
- stale H;
- bank reference.

Mandatory:
- Mae Klong release is not direct Qin into Damnoen Canal;
- stale H is not current H;
- unknown control states widen uncertainty;
- tide propagates through Tha Chin;
- no storage-stage/control data => no peak-cm.

## Mae Sai
Tests:
- transboundary catchment;
- rapid runoff;
- cross-border rain gap;
- DWR EWS.

Mandatory:
- catchment continues into Myanmar;
- global precipitation fallback;
- official warning does not become H/Q;
- ETA/depth eligibility stays honest.

## Nan
Tests:
- flash → river cascade;
- tributaries;
- wave routing;
- debris/obstruction.

Mandatory:
- flash can hand off to river flood;
- event doesn't end when local upstream area falls;
- capacity modifier supported.

## Ubon
Tests:
- large river;
- floodplain storage;
- Mekong boundary;
- bank-reference versioning;
- slow recession.

Mandatory:
- floodplain hysteresis;
- versioned bank/critical references;
- downstream boundary may be major river;
- no-data flash product != zero risk.

## Hat Yai
Tests:
- multiple inflows;
- urban bottleneck;
- lake/sea constraint;
- multi-wave;
- effective capacity;
- compound flood.

Mandatory:
- design capacity != effective capacity;
- second wave survives temporary decline;
- downstream lake/sea constrains Qout;
- event manager tracks several waves.

---

# 45. ACCEPTANCE RULES

Before public beta:

- Missing data is never converted to zero.
- Stale data is never silently current.
- Unverified units never enter physical equations.
- Bank references are time/version/spatially aware.
- No valid `S(H)` => no peak-cm output.
- Low terrain quality => no exact point-depth.
- Second waves remain after temporary local decline.
- Official warning is not hydraulic forcing.
- Cross-border catchments are not clipped at national border.
- Source outage uses cache/fallback and is visible.
- Every forecast exposes drivers and uncertainty.

---

# 46. HINDCAST / CALIBRATION

Withhold future data after forecast origin T0.

Evaluate:
```text
+6h
+12h
+24h
+48h
```

Metrics:
```text
H MAE/RMSE
peak-height error
peak-time error
bankfull-arrival error
duration error
Brier score
false negative
false positive
rise/stable/fall accuracy
```

Use five archetype basins as regression/calibration references.

---

# 47. PRECISION RULE

Use the best supported answer, not the most numerically detailed answer.

Allowed when data is strong:
```text
มีแนวโน้มถึงตลิ่งใน 8–14 ชั่วโมง
Peak +20–40 ซม.
```

Required when risk is clear but quantitative hydraulics are weak:
```text
ความเสี่ยงสูงมาก
ระดับมีแนวโน้มเพิ่มขึ้น
ยังประเมินความสูงสูงสุดเป็นเซนติเมตรอย่างน่าเชื่อถือไม่ได้
```

---

# 48. IMPLEMENTATION PHASES

## Phase 1 — Data foundation
- source registry;
- connectors;
- canonical observations;
- QC;
- PostGIS graph;
- source health;
- regression harness.

## Phase 2 — Operational awareness
- current state;
- official warnings;
- map;
- location context;
- risk headline;
- upstream/downstream explanation;
- data quality;
- event/wave objects;
- Public UI v2.

## Phase 3 — Routing / flash / event forecast
- runoff;
- empirical routing;
- travel-time distributions;
- wave tracking;
- bankfull ETA where eligible;
- assimilation.

## Phase 4 — Quantitative hydraulic peak
- storage-stage;
- controls;
- quantitative H;
- peak above bank;
- duration.

## Phase 5 — Local exposure/depth
Only where terrain and hydraulic validation pass.

## Phase 6 — Nationwide calibration
Automated event detection, reach calibration, performance tracking, capability upgrades.

---

# 49. IMPLEMENTATION PRIORITY

```text
Correct semantics
> Robust ingestion
> Quality/freshness
> Graph correctness
> Event continuity
> Honest eligibility
> Forecast sophistication
> Exact depth
```

Do not reverse this order.

---

# 50. BLOCKERS — REPORT, DO NOT REDESIGN

Examples:
```text
RID inflow/outflow unit unverifiable
HII schema changed
DWR endpoint unavailable
gate state no public feed
conflicting bank reference
terrain too coarse
source license restriction
cross-border rain latency
```

Correct behavior:
```text
use defined fallback
lower eligibility/confidence
record blocker
report blocker
continue implementation
```

Incorrect:
```text
invent assumption
remove feature
redesign UX
change hazard model
guess units
```

---

# 51. LICENSING

Before commercial/public production:
- review HII/other non-commercial terms;
- review API-key/license restrictions;
- retain source attribution/provenance;
- do not silently swap semantics due to licensing.

---

# 52. REPOSITORY STRUCTURE — RECOMMENDED

```text
/app
  /api
  /config
  /models
  /services

/data
  /connectors
    /hii
    /dwr
    /tmd
    /rid
    /navy_tide
    /gistda
    /global_precip
    /terrain
  /normalization
  /quality

/hydrology
  /catchment
  /runoff
  /routing
  /events
  /controls
  /boundaries
  /storage
  /bank
  /exposure
  /assimilation
  /ensemble
  /eligibility
  /confidence

/graph
  /builder
  /topology
  /dynamic_state

/db
  /migrations
  /repositories

/web
  /map
  /location
  /events
  /layers
  /expert

/tests
  /unit
  /integration
  /regression
    /ban_phaeo
    /mae_sai
    /nan
    /ubon
    /hat_yai
```

---

# 53. FINAL FROZEN RULE SET

1. Water travels as identifiable events/waves.
2. Flash flood can become downstream river flood.
3. Falling local level does not imply event end.
4. Multi-wave events are first-class.
5. Catchments may cross national boundaries.
6. Water graph is dynamic.
7. Bank reference is versioned and spatially scoped.
8. Critical level is not automatically physical bank.
9. Floodplain has storage and memory.
10. Design capacity != effective capacity.
11. Pump/gate uncertainty is conditional.
12. Downstream boundary is first-class.
13. Sea tide must propagate before inland use.
14. Missing data != zero.
15. No data != no risk.
16. Unknown semantics = unavailable.
17. `Qin-Qout` does not directly equal `dH/dt`.
18. No valid storage-stage relation => no quantitative peak height.
19. Terrain quality controls point-depth eligibility.
20. River overflow height != property depth.
21. Uncertainty propagates end-to-end.
22. Ensemble variables are not assumed independent.
23. Observations are continuously assimilated.
24. Official warnings are independent evidence.
25. Eligibility is per output.
26. Confidence is per output.
27. Public UI answers questions, not datasets.
28. Public UI is map-first.
29. UX uses progressive disclosure.
30. Work implements; Work does not redesign.

---

# 54. DEFINITION OF DONE FOR WORK

Work is finished only when implementation:

- follows this specification;
- contains no hidden redesign;
- has DB migrations;
- has connectors or explicit blocker stubs;
- has canonical normalization;
- has semantic/freshness/QC handling;
- supports dynamic water graph;
- supports hydrologic events and multi-wave;
- has eligibility/confidence objects;
- exposes frozen APIs;
- implements Public UI v2 and Expert Mode separation;
- includes five regression fixtures/tests;
- documents blockers;
- passes stale/missing/unverified-data acceptance behavior;
- never outputs unsupported precision.

---

# 55. IMPLEMENTATION INSTRUCTION TO WORK

Use this document as the single source of truth.

**Do not conduct further product discovery.  
Do not redesign the system.  
Do not propose a different architecture unless an implementation impossibility is proven and explicitly approved by the user.  
Do not change UX/UI decisions.  
Do not simplify hydrologic logic to reduce implementation work.**

Start from Phase 1 and proceed in order.

For blockers:
1. use the defined fallback;
2. preserve API contract where possible;
3. mark unavailable capability explicitly;
4. report exact blocker/evidence;
5. continue code that does not require redesign.

**The next task is engineering implementation, not hydrologic/product/design discussion.**

---

# 56. REFERENCE ARCHETYPES

## Ban Phaeo
Lowland controlled canal, pumps/gates, tidal boundary, compound flood.

## Mae Sai
Transboundary rapid runoff / flash flood.

## Nan
Mountain headwater → tributary → main-river cascade.

## Ubon
Large river/floodplain storage and major-river downstream boundary.

## Hat Yai
Multiple inflows, constrained drainage, lake/sea boundary, multi-wave.

---

**END OF FROZEN MASTER IMPLEMENTATION SPECIFICATION**
