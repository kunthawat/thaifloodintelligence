# Thailand Flood Intelligence — Implementation Data Manifest v1

**Status:** FROZEN IMPLEMENTATION COMPANION  
**Companion to:** `thailand_flood_intelligence_master_implementation_spec.md`  
**Purpose:** make Work implementation-ready without reopening logic or UX/UI.

---

# 0. CODE-ONLY RULE

Work must implement this manifest and the Master Spec.

Work must NOT:
- redesign hydrologic logic;
- redesign UX/UI;
- invent units/datums/station IDs;
- treat missing data as zero or no-risk;
- use unverified semantics in physical equations;
- bypass eligibility to create fake forecast numbers.

If a source is unstable, authenticated, undocumented, or missing:
1. implement its connector contract;
2. health-check it;
3. use the specified fallback;
4. reduce eligibility/confidence;
5. expose the blocker in `/v1/data-quality`;
6. continue coding.

---

# 1. SOURCE STATUS LEGEND

```text
VERIFIED_PUBLIC
VERIFIED_RELATIVE_API
DISCOVER_AT_RUNTIME
DISCOVERED_UNSTABLE
KEY_REQUIRED
AUTH_REQUIRED
SEMANTICS_UNVERIFIED
OPTIONAL
DISABLED_BY_DEFAULT
```

---

# 2. REQUIRED `.env.example`

```dotenv
APP_ENV=development
APP_TIMEZONE=Asia/Bangkok
LOG_LEVEL=INFO
PUBLIC_BASE_URL=http://localhost:8000

POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=thai_flood
POSTGRES_USER=thai_flood
POSTGRES_PASSWORD=change_me
DATABASE_URL=postgresql+psycopg://thai_flood:change_me@db:5432/thai_flood
DATABASE_DSN=postgresql://thai_flood:change_me@db:5432/thai_flood

DATA_DIR=/data
STATIC_DATA_DIR=/data/static
RAW_DATA_DIR=/data/raw
CACHE_DATA_DIR=/data/cache
RASTER_DATA_DIR=/data/rasters
MODEL_DATA_DIR=/data/models

HII_DATASET_CATALOG_URL=https://data.go.th/th/dataset/water-level
HII_LEGACY_DAILY_URL_TEMPLATE=https://tiwrm.hii.or.th/DATA/REPORT/php/show_itcwater.php?sdate={date}
HII_LEGACY_GRAPH_URL_TEMPLATE=https://tiwrm.hii.or.th/DATA/REPORT/php/itc_graph2.php?id1={legacy_id}%2C
HII_PUBLIC_WARNING_URL=https://tiwrm.hii.or.th/thaiwater_l5/public/telemetering/wl/warning

THAIWATER_V3_ENABLED=false
THAIWATER_V3_BASE_URL=https://api-v3.thaiwater.net
THAIWATER_V3_WATERLEVEL_PATH=/api/v1/thaiwater30/public/waterlevel_load

DWR_EWS_WARNING_URL=https://ews.dwr.go.th/ews/warn_list.php
DWR_EWS_STATION_URL_TEMPLATE=https://ews.dwr.go.th/ews/list_temp.php?link={station_code}
DWR_TELE_SOUTHWEST_URL=https://tele-southwest.dwr.go.th/home/Index_HOME

TMD_RADAR_DISCOVERY_URL=https://weather.tmd.go.th/chn.php
TMD_QPE_PAGE_CANDIDATE=https://weather.tmd.go.th/composite/index_qpe.html
TMD_QPE_ASCII_CANDIDATE=https://weather.tmd.go.th/composite/compositeQPE_VTBB_latest.asc.zip

RID_DAM_CURRENT_URL=https://app.rid.go.th/reservoir/api/dam/public
RID_DAM_HISTORY_URL_TEMPLATE=https://app.rid.go.th/reservoir/api/dam/public/{date}
RID_RESERVOIR_CURRENT_URL=https://app.rid.go.th/reservoir/api/reservoir/public
RID_RESERVOIR_HISTORY_URL_TEMPLATE=https://app.rid.go.th/reservoir/api/reservoir/public/{date}

NAVY_TIDE_INDEX_URL=https://hydro.navy.mi.th/waterlaveltable

GISTDA_ENABLED=false
GISTDA_API_BASE=
GISTDA_API_KEY=
GISTDA_AUTH_HEADER=Authorization
GISTDA_AUTH_SCHEME=Bearer

IMERG_ENABLED=false
IMERG_GIS_ROOT=https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/
IMERG_USERNAME=
IMERG_PASSWORD=
IMERG_TOKEN=

HYDROSHEDS_DOWNLOAD_PAGE=https://www.hydrosheds.org/hydrosheds-core-downloads
HYDROBASINS_DOWNLOAD_PAGE=https://www.hydrosheds.org/products/hydrobasins
HYDRORIVERS_DOWNLOAD_PAGE=https://www.hydrosheds.org/products/hydrorivers
HYDROSHEDS_REGION=Asia
HYDROSHEDS_RESOLUTION=3s

LDD_LANDUSE_ADMIN_LAYER=https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_QUERY_WM/MapServer/5
LDD_LANDUSE_SUBBASIN_LAYER=https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_QUERY_WM/MapServer/8
LDD_SOIL_FEATURE_QUERY=https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_WM/FeatureServer/6/query

ENABLE_HII_LEGACY=true
ENABLE_DWR_EWS=true
ENABLE_TMD_RADAR=true
ENABLE_RID_RESERVOIR=true
ENABLE_NAVY_TIDE=true
ENABLE_LDD=true
ENABLE_HYDROSHEDS=true

ALLOW_UNVERIFIED_SEMANTICS_IN_PHYSICS=false
ALLOW_STALE_AS_CURRENT=false
ALLOW_POINT_DEPTH_WITH_T3_T4_TERRAIN=false
```

Credentials remain blank intentionally. A connector without credentials reports `NOT_CONFIGURED`, not `SOURCE_ERROR`.

---

# 3. POSTGIS BOOTSTRAP

Create `docker-compose.yml`:

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-thai_flood}
      POSTGRES_USER: ${POSTGRES_USER:-thai_flood}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-change_me}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./db/bootstrap:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-thai_flood} -d ${POSTGRES_DB:-thai_flood}"]
      interval: 5s
      timeout: 5s
      retries: 20

volumes:
  postgres_data:
```

If this exact image tag is unavailable, use the nearest PostgreSQL 16 + PostGIS 3.x image. This is an infrastructure patch only.

Create `db/bootstrap/000_extensions.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Do not require TimescaleDB in Phase 1. Use native PostgreSQL partitioning.

Canonical horizontal geometry storage: `EPSG:4326`.  
Web rendering may transform to `EPSG:3857`.  
Vertical datum is separate and must never be inferred from horizontal CRS.

---

# 4. MIGRATION ORDER

```text
001_types.sql
010_sources.sql
020_geography.sql
030_network.sql
040_stations.sql
050_observations.sql
060_controls_boundaries.sql
070_bank_storage.sql
080_events.sql
090_forecasts.sql
100_warnings_impacts.sql
110_indexes.sql
120_seed_sources.sql
130_seed_stations.sql
```

---

# 5. SQL TYPES

```sql
CREATE TYPE semantic_status AS ENUM ('VERIFIED','PARTIAL','UNVERIFIED');

CREATE TYPE quality_state AS ENUM (
  'VALID','VALID_ZERO','MISSING','STALE','SUSPECT',
  'NOT_SUPPORTED','SOURCE_ERROR','ESTIMATED','NOT_CONFIGURED'
);

CREATE TYPE observation_type AS ENUM (
  'OBSERVED','DERIVED','FORECAST','ESTIMATED',
  'CONFIRMED_IMPACT','OFFICIAL_WARNING'
);

CREATE TYPE hazard_type AS ENUM (
  'RIVER_OVERFLOW','FLASH_FLOOD','LOCAL_RAIN','COASTAL_TIDAL','COMPOUND'
);

CREATE TYPE network_node_type AS ENUM (
  'SOURCE','CATCHMENT','SUBCATCHMENT','HEADWATER','GAUGE',
  'JUNCTION','CONFLUENCE','RESERVOIR','DIVERSION','GATE','PUMP',
  'CANAL_CONNECTION','TIDE_BOUNDARY','OUTLET','FLOODPLAIN_STORAGE'
);

CREATE TYPE network_edge_type AS ENUM (
  'RIVER_REACH','CREEK','CANAL','CONTROLLED_CANAL','DIVERSION',
  'GATE_PATH','PUMP_PATH','FLOODPLAIN_CONNECTION','ESTUARY'
);

CREATE TYPE edge_direction_type AS ENUM (
  'FORWARD','REVERSE','BIDIRECTIONAL','CONTROLLED','DYNAMIC'
);

CREATE TYPE boundary_type AS ENUM (
  'SEA','TIDAL_RIVER','RIVER','LAKE','RESERVOIR','CONTROLLED_CANAL','UNKNOWN'
);

CREATE TYPE bank_reference_type AS ENUM (
  'SURVEYED_BANK','OFFICIAL_STATION_BANK','LEVEE_CREST',
  'OPERATIONAL_CRITICAL_LEVEL','HISTORICAL_BANKFULL','DEM_ESTIMATE'
);

CREATE TYPE event_state AS ENUM (
  'GENERATING','HEADWATER_ROUTING','TRIBUTARY_ROUTING',
  'MAIN_RIVER_ROUTING','FLOODPLAIN_FILLING','RECESSION','ENDED'
);

CREATE TYPE wave_state AS ENUM (
  'FORECAST','GENERATING','IN_TRANSIT','ARRIVING','PASSING','PASSED','DISSIPATED'
);

CREATE TYPE floodplain_state_type AS ENUM (
  'DRY','FILLING','CONNECTED','DRAINING','ISOLATED_PONDING'
);

CREATE TYPE confidence_level AS ENUM ('HIGH','MEDIUM','LOW','UNAVAILABLE');
```

---

# 6. CORE SQL SCHEMA

## Sources

```sql
CREATE TABLE source_registry (
  source_id text PRIMARY KEY,
  provider text NOT NULL,
  dataset text NOT NULL,
  endpoint_type text NOT NULL,
  base_url text,
  native_unit text,
  native_datum text,
  native_timezone text,
  aggregation_interval interval,
  semantics_status semantic_status NOT NULL DEFAULT 'UNVERIFIED',
  license text,
  commercial_use_status text,
  expected_update_pattern text,
  freshness_warn_after interval,
  freshness_reject_after interval,
  priority integer NOT NULL DEFAULT 100,
  fallback_group text,
  auth_required boolean NOT NULL DEFAULT false,
  parser_version text NOT NULL DEFAULT '1',
  schema_valid_from timestamptz,
  schema_valid_to timestamptz,
  enabled boolean NOT NULL DEFAULT true,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_health (
  source_id text NOT NULL REFERENCES source_registry(source_id),
  checked_at timestamptz NOT NULL DEFAULT now(),
  status quality_state NOT NULL,
  http_status integer,
  latency_ms integer,
  last_observed_at timestamptz,
  last_success_at timestamptz,
  error_code text,
  error_message text,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (source_id, checked_at)
);

CREATE TABLE source_schema_versions (
  source_id text NOT NULL REFERENCES source_registry(source_id),
  schema_version text NOT NULL,
  valid_from timestamptz,
  valid_to timestamptz,
  schema_definition jsonb NOT NULL,
  parser_version text NOT NULL,
  PRIMARY KEY (source_id, schema_version)
);
```

## Geography

```sql
CREATE TABLE basins (
  basin_id text PRIMARY KEY,
  name_th text,
  name_en text,
  source text NOT NULL,
  source_id text,
  level integer,
  geom geometry(MultiPolygon,4326) NOT NULL,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE catchments (
  catchment_id text PRIMARY KEY,
  parent_catchment_id text REFERENCES catchments(catchment_id),
  basin_id text REFERENCES basins(basin_id),
  source text NOT NULL,
  source_id text,
  area_km2 double precision,
  mean_elevation_m double precision,
  relief_m double precision,
  mean_slope double precision,
  max_slope double precision,
  flow_length_m double precision,
  time_of_concentration_min double precision,
  drainage_density double precision,
  terrain_quality_tier text,
  transboundary boolean NOT NULL DEFAULT false,
  geom geometry(MultiPolygon,4326) NOT NULL,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE terrain_products (
  terrain_product_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  provider text NOT NULL,
  product_type text NOT NULL,
  resolution_m double precision,
  horizontal_crs text,
  vertical_datum text,
  quality_tier text NOT NULL,
  uri text NOT NULL,
  bbox geometry(Polygon,4326),
  valid_from timestamptz,
  imported_at timestamptz NOT NULL DEFAULT now(),
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

## Dynamic network

```sql
CREATE TABLE network_nodes (
  node_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_type network_node_type NOT NULL,
  canonical_name text,
  provider text,
  provider_id text,
  catchment_id text REFERENCES catchments(catchment_id),
  geom geometry(Point,4326),
  elevation_m double precision,
  vertical_datum text,
  confidence double precision CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE network_edges (
  edge_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  edge_type network_edge_type NOT NULL,
  canonical_name text,
  from_node_id uuid NOT NULL REFERENCES network_nodes(node_id),
  to_node_id uuid NOT NULL REFERENCES network_nodes(node_id),
  direction_type edge_direction_type NOT NULL,
  geom geometry(MultiLineString,4326),
  length_m double precision,
  slope double precision,
  capacity_design_m3s double precision,
  capacity_effective_m3s double precision,
  travel_time_model jsonb,
  network_confidence double precision CHECK (
    network_confidence IS NULL OR network_confidence BETWEEN 0 AND 1
  ),
  hydraulic_parameters_verified boolean NOT NULL DEFAULT false,
  valid_from timestamptz,
  valid_to timestamptz,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE edge_versions (
  edge_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  edge_id uuid NOT NULL REFERENCES network_edges(edge_id),
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  direction_type edge_direction_type,
  capacity_design_m3s double precision,
  geometry_version text,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

## Stations

```sql
CREATE TABLE stations (
  station_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_code text UNIQUE,
  canonical_name_th text,
  canonical_name_en text,
  river_or_waterway text,
  province text,
  district text,
  subdistrict text,
  geom geometry(Point,4326),
  node_id uuid REFERENCES network_nodes(node_id),
  active boolean NOT NULL DEFAULT true,
  metadata_confidence double precision,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE station_source_map (
  station_source_map_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id uuid NOT NULL REFERENCES stations(station_id),
  source_id text NOT NULL REFERENCES source_registry(source_id),
  provider_station_code text,
  provider_station_id text,
  provider_station_name text,
  mapping_status text NOT NULL,
  verified_at timestamptz,
  verification_method text,
  notes text
);
```

Application mapping statuses:

```text
VERIFIED
VERIFIED_NAME_ONLY
CANDIDATE_REQUIRES_NAME_MATCH
CONFLICT
UNRESOLVED
```

## Observations

```sql
CREATE TABLE observations (
  observation_id bigserial,
  entity_type text NOT NULL,
  entity_id text NOT NULL,
  variable text NOT NULL,
  value double precision,
  unit text,
  datum text,
  observed_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  source_id text NOT NULL REFERENCES source_registry(source_id),
  source_record_id text,
  quality_state quality_state NOT NULL,
  quality_score double precision CHECK (
    quality_score IS NULL OR quality_score BETWEEN 0 AND 1
  ),
  observation_type observation_type NOT NULL,
  raw_payload jsonb,
  PRIMARY KEY (observation_id,observed_at)
) PARTITION BY RANGE (observed_at);

CREATE TABLE observations_default
PARTITION OF observations DEFAULT;

CREATE TABLE observation_quality (
  observation_id bigint NOT NULL,
  observed_at timestamptz NOT NULL,
  timestamp_ok boolean,
  range_ok boolean,
  spike_ok boolean,
  neighbour_ok boolean,
  freshness_ok boolean,
  unit_ok boolean,
  datum_ok boolean,
  semantics_ok boolean,
  reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY (observation_id,observed_at)
);
```

## Controls / boundaries

```sql
CREATE TABLE gates (
  gate_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id uuid REFERENCES network_nodes(node_id),
  canonical_name text NOT NULL,
  provider text,
  provider_id text,
  gate_count integer,
  gate_width_m double precision,
  capacity_design_m3s double precision,
  geom geometry(Point,4326),
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE pumps (
  pump_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id uuid REFERENCES network_nodes(node_id),
  canonical_name text NOT NULL,
  provider text,
  provider_id text,
  pump_count integer,
  capacity_each_m3s double precision,
  capacity_design_total_m3s double precision,
  geom geometry(Point,4326),
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE control_state (
  control_state_id bigserial PRIMARY KEY,
  control_type text NOT NULL,
  control_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  availability double precision,
  head_factor double precision,
  blockage_factor double precision,
  operation_factor double precision,
  gate_opening_m double precision,
  upstream_h_m double precision,
  downstream_h_m double precision,
  q_effective_m3s double precision,
  source_id text REFERENCES source_registry(source_id),
  quality_state quality_state NOT NULL,
  confidence double precision,
  raw_payload jsonb
);

CREATE TABLE downstream_boundaries (
  boundary_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  boundary_type boundary_type NOT NULL,
  canonical_name text NOT NULL,
  node_id uuid REFERENCES network_nodes(node_id),
  geom geometry(Point,4326),
  propagation_model jsonb,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE boundary_state (
  boundary_state_id bigserial PRIMARY KEY,
  boundary_id uuid NOT NULL REFERENCES downstream_boundaries(boundary_id),
  observed_at timestamptz NOT NULL,
  stage_m double precision,
  stage_datum text,
  astronomical_tide_m double precision,
  observed_sea_level_m double precision,
  surge_residual_m double precision,
  source_id text REFERENCES source_registry(source_id),
  quality_state quality_state NOT NULL,
  confidence double precision,
  raw_payload jsonb
);
```

## Banks / storage

```sql
CREATE TABLE bank_references (
  bank_reference_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reach_id uuid REFERENCES network_edges(edge_id),
  station_id uuid REFERENCES stations(station_id),
  elevation_m double precision NOT NULL,
  datum text NOT NULL,
  reference_type bank_reference_type NOT NULL,
  valid_from timestamptz,
  valid_to timestamptz,
  source_id text REFERENCES source_registry(source_id),
  source_published_at timestamptz,
  left_bank_elevation_m double precision,
  right_bank_elevation_m double precision,
  representative_geom geometry(Geometry,4326),
  spatial_extent_m double precision,
  confidence double precision,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE storage_nodes (
  storage_node_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id uuid REFERENCES network_nodes(node_id),
  storage_type text NOT NULL,
  canonical_name text,
  connection_elevation_m double precision,
  datum text,
  terrain_quality_tier text,
  confidence double precision,
  geom geometry(MultiPolygon,4326),
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE stage_storage_curves (
  stage_storage_curve_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  storage_node_id uuid NOT NULL REFERENCES storage_nodes(storage_node_id),
  method text NOT NULL,
  datum text,
  source_id text REFERENCES source_registry(source_id),
  valid_from timestamptz,
  valid_to timestamptz,
  verified boolean NOT NULL DEFAULT false,
  points jsonb NOT NULL,
  confidence double precision
);

CREATE TABLE floodplain_state (
  floodplain_state_id bigserial PRIMARY KEY,
  storage_node_id uuid NOT NULL REFERENCES storage_nodes(storage_node_id),
  observed_at timestamptz NOT NULL,
  state floodplain_state_type NOT NULL,
  volume_m3 double precision,
  stage_m double precision,
  source text,
  confidence double precision,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

## Events / waves

```sql
CREATE TABLE hydrologic_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_name text,
  dominant_hazard hazard_type,
  state event_state NOT NULL,
  origin_catchment_id text REFERENCES catchments(catchment_id),
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  official_warning_present boolean NOT NULL DEFAULT false,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE event_waves (
  wave_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES hydrologic_events(event_id),
  parent_wave_id uuid REFERENCES event_waves(wave_id),
  state wave_state NOT NULL,
  origin_catchment_id text REFERENCES catchments(catchment_id),
  current_edge_id uuid REFERENCES network_edges(edge_id),
  generated_at timestamptz,
  eta_start timestamptz,
  eta_p50 timestamptz,
  eta_end timestamptz,
  peak_q_p10 double precision,
  peak_q_p50 double precision,
  peak_q_p90 double precision,
  confidence double precision,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE runoff_pulses (
  runoff_pulse_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid REFERENCES hydrologic_events(event_id),
  wave_id uuid REFERENCES event_waves(wave_id),
  catchment_id text NOT NULL REFERENCES catchments(catchment_id),
  valid_from timestamptz NOT NULL,
  valid_to timestamptz NOT NULL,
  runoff_volume_m3 double precision,
  q_series jsonb,
  method text NOT NULL,
  confidence double precision,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

## Forecasts

```sql
CREATE TABLE forecast_runs (
  forecast_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_version text NOT NULL,
  generated_at timestamptz NOT NULL DEFAULT now(),
  forecast_origin timestamptz NOT NULL,
  horizon_end timestamptz NOT NULL,
  event_id uuid REFERENCES hydrologic_events(event_id),
  status text NOT NULL,
  input_snapshot jsonb NOT NULL,
  source_health_snapshot jsonb NOT NULL,
  assumptions jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE forecast_members (
  forecast_member_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  forecast_run_id uuid NOT NULL REFERENCES forecast_runs(forecast_run_id),
  member_no integer NOT NULL,
  scenario_weight double precision NOT NULL DEFAULT 1.0,
  scenario_inputs jsonb NOT NULL,
  UNIQUE(forecast_run_id,member_no)
);

CREATE TABLE forecast_outputs (
  forecast_output_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  forecast_run_id uuid NOT NULL REFERENCES forecast_runs(forecast_run_id),
  target_type text NOT NULL,
  target_id text NOT NULL,
  variable text NOT NULL,
  valid_at timestamptz,
  p10 double precision,
  p50 double precision,
  p90 double precision,
  probability double precision,
  unit text,
  datum text,
  eligible boolean NOT NULL,
  eligibility_reason text,
  confidence confidence_level NOT NULL,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

## Warnings / impacts

```sql
CREATE TABLE official_warnings (
  warning_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id text NOT NULL REFERENCES source_registry(source_id),
  provider_warning_id text,
  issued_at timestamptz NOT NULL,
  valid_from timestamptz,
  valid_to timestamptz,
  severity text,
  hazard_type hazard_type,
  title text,
  message text,
  geom geometry(Geometry,4326),
  raw_payload jsonb
);

CREATE TABLE flood_extents (
  flood_extent_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id text NOT NULL REFERENCES source_registry(source_id),
  observed_at timestamptz,
  period_label text,
  observation_type observation_type NOT NULL DEFAULT 'CONFIRMED_IMPACT',
  geom geometry(MultiPolygon,4326),
  confidence double precision,
  raw_payload jsonb
);

CREATE TABLE location_exposure (
  exposure_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  forecast_run_id uuid REFERENCES forecast_runs(forecast_run_id),
  location_geom geometry(Point,4326) NOT NULL,
  hazard_type hazard_type,
  probability double precision,
  depth_p10_m double precision,
  depth_p50_m double precision,
  depth_p90_m double precision,
  depth_eligible boolean NOT NULL DEFAULT false,
  depth_ineligible_reason text,
  terrain_quality_tier text,
  confidence confidence_level NOT NULL,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

---

# 7. REQUIRED INDEXES

```sql
CREATE INDEX idx_basins_geom ON basins USING gist(geom);
CREATE INDEX idx_catchments_geom ON catchments USING gist(geom);
CREATE INDEX idx_network_nodes_geom ON network_nodes USING gist(geom);
CREATE INDEX idx_network_edges_geom ON network_edges USING gist(geom);
CREATE INDEX idx_stations_geom ON stations USING gist(geom);
CREATE INDEX idx_bank_reference_geom ON bank_references USING gist(representative_geom);
CREATE INDEX idx_storage_geom ON storage_nodes USING gist(geom);
CREATE INDEX idx_warning_geom ON official_warnings USING gist(geom);
CREATE INDEX idx_flood_extent_geom ON flood_extents USING gist(geom);
CREATE INDEX idx_location_exposure_geom ON location_exposure USING gist(location_geom);

CREATE INDEX idx_observations_entity_var_time
  ON observations(entity_type,entity_id,variable,observed_at DESC);
CREATE INDEX idx_observations_source_time
  ON observations(source_id,observed_at DESC);
CREATE INDEX idx_control_state_time
  ON control_state(control_type,control_id,observed_at DESC);
CREATE INDEX idx_boundary_state_time
  ON boundary_state(boundary_id,observed_at DESC);
CREATE INDEX idx_event_waves_event_state
  ON event_waves(event_id,state);
CREATE INDEX idx_forecast_outputs_target
  ON forecast_outputs(target_type,target_id,variable,valid_at);
```

---

# 8. CONCRETE SOURCE REGISTRY

## HII water-level catalog

**Status:** `VERIFIED_PUBLIC`  
**URL:** `https://data.go.th/th/dataset/water-level`  
**Auth:** none

Verified semantics:
- water level every 10 minutes;
- unit `m MSL / ม.รทก.`;
- historical data from around 2012;
- from February 2026 uses Thaiwater.Standard format;
- missing values include `-999`, `999999`, `9999`, `-`;
- catalog currently reports CC Attribution Non-Commercial.

Use for metadata/archive discovery and calibration. Historical archive is never live current-state data.

## HII archive layout

Official catalog describes:

```text
0all_stn_metadata.csv
YYYY/
  YYYYMM/
    <station>.csv
0zip_file/
  <year>.zip
```

The connector must discover the current archive root from the official resource/catalog rather than permanently assuming a hidden host path.

## HII legacy daily

**Status:** `DISCOVERED_UNSTABLE`

```text
https://tiwrm.hii.or.th/DATA/REPORT/php/show_itcwater.php?sdate={YYYY-MM-DD}
```

Historical fallback/discovery only. Timeouts become `SOURCE_ERROR`.

## HII legacy station graph

**Status:** `DISCOVERED_UNSTABLE`

```text
https://tiwrm.hii.or.th/DATA/REPORT/php/itc_graph2.php?id1={legacy_id}%2C
```

Never persist a numeric provider ID until the returned station code/name matches the expected canonical station.

## HII public warning page

**Status:** `DISCOVERED_UNSTABLE`

```text
https://tiwrm.hii.or.th/thaiwater_l5/public/telemetering/wl/warning
```

Use as current/public cross-check only if timestamp and parse quality are valid.

## ThaiWater v3 candidate

**Status:** `DISABLED_BY_DEFAULT`

```text
https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load
```

Enable only after runtime schema/terms/freshness verification.

---

# 9. DWR EWS

## Warning list

```text
https://ews.dwr.go.th/ews/warn_list.php
```

Observed filter params include:

```text
on_basin
on_dept
on_num
on_prov
on_status
on_yr
```

Known warning context includes:
- 15-minute rain;
- 12/24/48h accumulated rain;
- water level;
- timestamp;
- warning status.

Site may timeout. Cache/backoff mandatory.

## Station time series

```text
https://ews.dwr.go.th/ews/list_temp.php?link={STATION_CODE}
```

Example:

```text
https://ews.dwr.go.th/ews/list_temp.php?link=STN0168
```

Reference regression station:

```text
STN0029  Mae Sai
```

Normalize all times to canonical timezone-aware timestamps.

## Southwest telemetry portal

Optional discovery:

```text
https://tele-southwest.dwr.go.th/home/Index_HOME
```

Do not double-count if observations originate from HII/RID already.

---

# 10. TMD RADAR / QPE

Official discovery:

```text
https://weather.tmd.go.th/chn.php
```

It advertises:
- Nationwide composite;
- Nationwide QPE;
- Nationwide QPE ASCII;
- individual radars including Chiang Rai, Samut Songkhram, Ubon, Hat Yai, etc.

TMD page timestamps are UTC.

The QPE ASCII link discovered from the official page currently points to a target resembling:

```text
https://weather.tmd.go.th/composite/compositeQPE_VTBB_latest.asc.zip
```

During verification it returned `404`.

Therefore the connector MUST:

```text
GET /chn.php
→ find "Nationwide QPE Ascii file"
→ resolve current href dynamically
→ GET href
→ validate ZIP/ASCII/header/units
→ if 404 or invalid: SOURCE_ERROR for numeric QPE, then fallback
```

Never interpret QPE download failure as zero rainfall.

---

# 11. RID RESERVOIR API

Large dams:

```text
GET https://app.rid.go.th/reservoir/api/dam/public
GET https://app.rid.go.th/reservoir/api/dam/public/{YYYY-MM-DD}
```

Official fields:

```text
date total region id name owner
capacity storage active_storage dead_storage
volume percent_storage inflow outflow
```

Verified units:

```text
capacity/storage/active_storage/dead_storage/volume = million m3
percent_storage = percent
```

`inflow` and `outflow` units are **not documented in the current API docs**.

Store them raw:

```text
RID_RAW_INFLOW
RID_RAW_OUTFLOW
unit = null
semantic_status = UNVERIFIED
```

They MUST NOT enter physical mass balance until independently verified.

Medium reservoirs:

```text
GET https://app.rid.go.th/reservoir/api/reservoir/public
GET https://app.rid.go.th/reservoir/api/reservoir/public/{YYYY-MM-DD}
```

Same inflow/outflow rule applies.

---

# 12. ROYAL THAI NAVY TIDE

Discovery/index:

```text
https://hydro.navy.mi.th/waterlaveltable
```

Use the current-year station table and prefer MSL-referenced download.

Runtime algorithm:

```text
GET index
→ locate current year
→ station row
→ Mean Sea Level link
→ download PDF
→ parse hourly prediction
→ store FORECAST
```

2026 test fixtures:

```text
Pak Nam Tha Chin MSL:
https://hydro.navy.mi.th/storage/frontend/article/23007/file/th/TC2026msl.pdf

Pak Nam Mae Klong MSL:
https://hydro.navy.mi.th/storage/frontend/article/23009/file/th/MK2026mls.pdf
```

Do not hard-code annual article IDs for future years.

Time = Thailand standard time (UTC+7).  
Prediction != observed sea level.  
Do not inject coastal tide directly into inland gate H; use tidal-river propagation.

---

# 13. GISTDA DISASTER API

Official docs:

```text
https://disaster.gistda.or.th/services/open-api
```

API key registration is explicitly offered.

Verified relative paths:

```text
/features/flood/1day
/features/flood/3days
/features/flood/7days
/features/flood/30days
/features/flood-freq
/features/water_hyacinth

/maps/flood/1day/wms
/maps/flood/3days/wms
/maps/flood/7days/wms
/maps/flood/30days/wms
/maps/flood-freq/wms

/maps/flood/1day/wmts
/maps/flood/3days/wmts
/maps/flood/7days/wmts
/maps/flood/30days/wmts
/maps/flood-freq/wmts

/maps/flood/1day/tms/{z}/{x}/{y}
/maps/flood/3days/tms/{z}/{x}/{y}
/maps/flood/7days/tms/{z}/{x}/{y}
/maps/flood/30days/tms/{z}/{x}/{y}
/maps/flood-freq/tms/{z}/{x}/{y}
```

Exact API base after account setup goes in:

```dotenv
GISTDA_API_BASE=
GISTDA_API_KEY=
```

Until configured: `NOT_CONFIGURED`, not application failure.

Empty GISTDA result never proves no flood.

---

# 14. HYDROSHEDS / HYDROBASINS / HYDRORIVERS

HydroSHEDS v1.1:

```text
https://www.hydrosheds.org/hydrosheds-core-downloads
```

Required:
```text
Conditioned DEM, 3 arc-second, Asia
Flow Direction, 3 arc-second, Asia
Flow Accumulation ACC, 3 arc-second, Asia
```

GeoTIFF, WGS84. Approx 90m at equator.

Official no-data:
```text
DEM/CON: 32767
DIR: 255
ACC/ACA: 4294967295
```

HydroBASINS:

```text
https://www.hydrosheds.org/products/hydrobasins
```

Import full Asia standard levels 1–12. Do not clip topology at Thailand border.

Suggested operational use:
```text
overview: levels 4–6
forecast catchments: levels 8–10
local refinement: derive from DEM when required
```

Preserve all original levels/IDs.

HydroRIVERS:

```text
https://www.hydrosheds.org/products/hydrorivers
```

Import Asia vector data. Preserve topology fields such as:

```text
HYRIV_ID
NEXT_DOWN
MAIN_RIV
LENGTH_KM
DIST_DN_KM
DIST_UP_KM
CATCH_SKM
UPLAND_SKM
```

HydroRIVERS is natural-river skeleton only; never fabricate artificial canals from it.

---

# 15. NASA IMERG

Official product:

```text
https://gpm.nasa.gov/data/imerg
```

GIS root:

```text
https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/
```

IMERG Early Run characteristics:
- ~30-minute product;
- ~0.1 degree / ~10 km;
- minimum latency ~4 hours.

Use:
- cross-border rainfall gap filling;
- broader antecedent rain;
- transboundary catchment support.

Not sole 0–2h flash trigger where TMD/DWR/HII exist.

Registration/auth may be required:

```dotenv
IMERG_USERNAME=
IMERG_PASSWORD=
IMERG_TOKEN=
```

Missing auth -> `NOT_CONFIGURED`, cross-border confidence decreases.

---

# 16. LDD LAND USE / SOIL

Combined land-use/soil admin layer:

```text
https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_QUERY_WM/MapServer/5
```

Known fields:

```text
LUCODE DES_TH DES_EN Lu_gr
PROV_CODE AMP_CODE TAM_CODE
Soil_Sym Soil_Ss Soil_gr Soil_gr_des
```

Native spatial reference: EPSG:3857.

Subbasin layer:

```text
https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_QUERY_WM/MapServer/8
```

Soil query endpoint:

```text
https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_WM/FeatureServer/6/query
```

Point-query pattern:

```text
geometry=<lon>,<lat>
geometryType=esriGeometryPoint
inSR=4326
spatialRel=esriSpatialRelIntersects
outFields=*
returnGeometry=false
f=json
```

Transform coordinates if a particular service layer requires EPSG:3857.

---

# 17. HII NORMALIZATION

```text
water_level -> WATER_LEVEL
unit -> m
datum -> MSL only when source explicitly states m MSL/ม.รทก.
archive interval -> 10 min
```

Missing:

```python
HII_MISSING = {"-999","999999","9999","-", "", None}
```

Select parser by observation date/schema version, especially Feb 2026 onward.

---

# 18. RID NORMALIZATION

Safe:

```text
capacity -> RESERVOIR_CAPACITY_MCM
storage -> RESERVOIR_STORAGE_MCM
active_storage -> RESERVOIR_ACTIVE_STORAGE_MCM
dead_storage -> RESERVOIR_DEAD_STORAGE_MCM
volume -> RESERVOIR_VOLUME_MCM
percent_storage -> RESERVOIR_PERCENT_STORAGE
```

Unsafe:
```text
inflow/outflow -> raw only, unverified unit
```

---

# 19. NAVY NORMALIZATION

Prefer MSL edition:

```text
station
predicted_at
predicted_level_m
datum=MSL
observation_type=FORECAST
```

If only LLW:
- store `datum=LLW`;
- do not compare with MSL until verified offset exists.

---

# 20. STATION SEEDS

Create `config/station_seeds.yaml`:

```yaml
stations:
  - canonical_code: "BP-BAN-PHAEO"
    canonical_name_th: "บ้านแพ้ว"
    river_or_waterway: "คลองดำเนินสะดวก"
    province: "สมุทรสาคร"
    district: "บ้านแพ้ว"
    source: "HII"
    provider_station_code: null
    provider_station_id: null
    mapping_status: "VERIFIED_NAME_ONLY"
    known_bank_reference:
      value_m: 0.96
      datum: "MSL"
      type: "OFFICIAL_STATION_BANK"
      status: "REQUIRES_RUNTIME_RECONFIRMATION"
    notes: "Do not use stale 2026-09-26 H≈0.70 m as current."

  - canonical_code: "MK03"
    canonical_name_th: "ปตร.บางนกแขวก"
    river_or_waterway: "คลองดำเนินสะดวก/แม่กลอง"
    source: "HII legacy"
    provider_station_code: "MK03"
    provider_station_id: null
    mapping_status: "CONFLICT"
    candidate_provider_ids: ["534","1113"]
    notes: "Conflicting legacy IDs seen during R&D. Verify returned name/code before persisting."

  - canonical_code: "K.57"
    canonical_name_th: "บางคนที"
    river_or_waterway: "แม่น้ำแม่กลอง"
    source: "HII legacy"
    provider_station_code: "K.57"
    provider_station_id: "1116"
    mapping_status: "CANDIDATE_REQUIRES_NAME_MATCH"

  - canonical_code: "K.58A"
    canonical_name_th: "บ้านเขาพัง"
    river_or_waterway: "แควน้อย"
    source: "HII legacy"
    provider_station_code: "K.58A"
    provider_station_id: "1027"
    mapping_status: "CANDIDATE_REQUIRES_NAME_MATCH"

  - canonical_code: "TC.9"
    canonical_name_th: "วัดท่ากระบือ"
    river_or_waterway: "แม่น้ำท่าจีน"
    province: "สมุทรสาคร"
    source: "HII legacy"
    provider_station_code: "TC.9"
    provider_station_id: "1112"
    mapping_status: "CANDIDATE_REQUIRES_NAME_MATCH"

  - canonical_code: "STN0029"
    canonical_name_th: "สถานี EWS แม่สาย"
    province: "เชียงราย"
    district: "แม่สาย"
    source: "DWR EWS"
    provider_station_code: "STN0029"
    mapping_status: "VERIFIED_CODE"

  - canonical_code: "NAN001"
    canonical_name_th: "NAN001"
    river_or_waterway: "ลุ่มน้ำน่าน"
    source: "HII archive"
    provider_station_code: "NAN001"
    mapping_status: "VERIFIED_CODE"

  - canonical_code: "NAN002"
    canonical_name_th: "NAN002"
    river_or_waterway: "ลุ่มน้ำน่าน"
    source: "HII archive"
    provider_station_code: "NAN002"
    mapping_status: "VERIFIED_CODE"

  - canonical_code: "NAN003"
    canonical_name_th: "NAN003"
    river_or_waterway: "ลุ่มน้ำน่าน"
    source: "HII archive"
    provider_station_code: "NAN003"
    mapping_status: "VERIFIED_CODE"

  - canonical_code: "NAN009"
    canonical_name_th: "NAN009"
    river_or_waterway: "ลุ่มน้ำน่าน"
    source: "HII archive"
    provider_station_code: "NAN009"
    mapping_status: "VERIFIED_CODE"

  - canonical_code: "M.7"
    canonical_name_th: "M.7 อุบลราชธานี"
    river_or_waterway: "แม่น้ำมูล"
    province: "อุบลราชธานี"
    source: "multi-source"
    provider_station_code: "M.7"
    mapping_status: "VERIFIED_NAME_ONLY"
    notes: "Bank/critical reference must be versioned; published values differ by date/source."

  - canonical_code: "X.44"
    canonical_name_th: "X.44 บ้านหาดใหญ่"
    river_or_waterway: "คลองอู่ตะเภา"
    province: "สงขลา"
    source: "multi-source"
    provider_station_code: "X.44"
    mapping_status: "VERIFIED_NAME_ONLY"
```

Provider numeric IDs marked candidate must pass exact station code/name verification.

---

# 21. POLLING / FRESHNESS DEFAULTS

| Source | Poll | Warn stale | Reject as current |
|---|---:|---:|---:|
| HII current/public if available | 5–10 min | 30 min | 2 h |
| HII archive | nightly/batch | n/a | never current |
| DWR EWS | 5–10 min | 30 min | 2 h |
| DWR station | 5–15 min | 30 min | 2 h |
| TMD radar/QPE | 5–10 min | 20 min | 60 min |
| RID reservoir | 1 h | 6 h | 48 h for operational current use |
| Navy tide | pre-ingest annual | metadata 30 d | year expiry |
| GISTDA | 1–6 h/API-limit aware | 24 h | period semantics |
| IMERG Early | hourly availability | 6 h | 12 h for rapid trigger |
| LDD | static/cache | 180 d | no immediate reject |
| HydroSHEDS/HydroBASINS/HydroRIVERS | static/versioned | n/a | versioned |

A rejected/stale observation can remain historical but cannot silently become current.

---

# 22. FALLBACK CHAINS

## Stage/H

```text
1 verified fresh official feed
2 verified alternate connected gauge/source
3 state estimator using hydraulic neighbours
4 last observation with explicit age + uncertainty
5 hazard-only / warning mode
```

Historical HII archive is calibration, not live fallback.

## Rain — Thailand

```text
TMD QPE/radar
→ DWR/HII gauges
→ other verified telemetry
→ IMERG/global
```

## Rain — cross-border

```text
verified neighbor/local source if implemented
→ IMERG/global
→ forecast precipitation ensemble
```

## Coast/downstream

```text
observed sea level if later verified
→ Navy predicted tide
→ boundary numeric forcing unavailable + uncertainty
```

## Pump/gate

```text
verified telemetry
→ recent operational report
→ last-known state with time decay
→ conditional ensemble
```

Unknown never defaults to fully on/off.

---

# 23. TERRAIN BOOTSTRAP

Implement:

```bash
python -m scripts.bootstrap_terrain --region asia --resolution 3s
python -m scripts.bootstrap_hydrobasins --region asia
python -m scripts.bootstrap_hydrorivers --region asia
```

`bootstrap_terrain` must:
1. fetch official HydroSHEDS page;
2. resolve Asia 3s conditioned DEM;
3. resolve Asia 3s flow direction;
4. resolve Asia 3s flow accumulation ACC;
5. download originals;
6. validate GeoTIFF/WGS84/no-data;
7. archive originals;
8. build optimized derivatives/COGs separately;
9. register checksum/version in `terrain_products`.

HydroBASINS/HydroRIVERS import full Asia topology and must not clip at Thai border.

Terrain bootstrap fails if required DEM/DIR/ACC is missing or invalid.

Default quality:
```text
HydroSHEDS 3s mountainous screening = T3
HydroSHEDS 3s flat/coastal exact depth = T4 restriction
```

---

# 24. CONNECTOR INTERFACE

```python
class SourceConnector(Protocol):
    source_id: str

    async def healthcheck(self) -> SourceHealth: ...
    async def discover(self) -> DiscoveryResult: ...
    async def fetch(self, window: TimeWindow | None = None) -> list[RawRecord]: ...
    def normalize(self, raw: RawRecord) -> list[CanonicalObservation]: ...
    def validate_semantics(self) -> SemanticValidation: ...
```

Static GIS:

```python
class StaticDatasetConnector(Protocol):
    source_id: str

    async def discover_version(self) -> DatasetVersion: ...
    async def download(self, version: DatasetVersion) -> list[Path]: ...
    def validate(self, paths: list[Path]) -> ValidationReport: ...
    def import_dataset(self, paths: list[Path]) -> ImportReport: ...
```

---

# 25. `/v1/data-quality` CONTRACT

Example valid:

```json
{
  "source_id": "tmd_radar_discovery",
  "status": "VALID",
  "last_check": "...",
  "last_success": "...",
  "last_observation": "...",
  "freshness": "FRESH",
  "semantics": "VERIFIED",
  "configured": true,
  "message": null
}
```

Missing GISTDA key:

```json
{
  "source_id": "gistda_flood",
  "status": "NOT_CONFIGURED",
  "configured": false,
  "message": "GISTDA_API_BASE/API key not configured"
}
```

TMD QPE target 404:

```json
{
  "source_id": "tmd_qpe_ascii",
  "status": "SOURCE_ERROR",
  "configured": true,
  "message": "Current discovery target returned 404; rainfall fallback active"
}
```

---

# 26. CONNECTOR ACCEPTANCE TESTS

## HII

```text
[ ] catalog retrieval or clean SOURCE_ERROR
[ ] 10-minute + m MSL semantics loaded
[ ] -999/999999/9999/- -> MISSING
[ ] post-Feb-2026 parser is schema/date aware
[ ] legacy timeout never blocks user API
[ ] numeric station ID rejected if returned station identity mismatches
```

## DWR

```text
[ ] warning timeout -> cache/backoff
[ ] STN0029 URL can be constructed
[ ] 15-minute timestamps parse when page available
[ ] warning stored OFFICIAL_WARNING, never as H/Q forcing
```

## TMD

```text
[ ] discovery parsed
[ ] UTC normalized
[ ] QPE ASCII href dynamically resolved
[ ] 404 != zero rain
```

## RID

```text
[ ] large/medium reservoir JSON parsed
[ ] MCM fields normalized
[ ] inflow/outflow blocked from physics while unit unverified
```

## Navy

```text
[ ] current-year table discovered
[ ] 2026 Pak Nam Tha Chin MSL fixture parse
[ ] 2026 Pak Nam Mae Klong MSL fixture parse
[ ] time interpreted UTC+7
[ ] observation_type remains FORECAST
```

## GISTDA

```text
[ ] no credential -> NOT_CONFIGURED
[ ] relative paths implemented
[ ] configured polygons -> CONFIRMED_IMPACT
[ ] empty result != no flood
```

## HydroSHEDS/HydroBASINS/HydroRIVERS

```text
[ ] Asia products import
[ ] topology preserved across border
[ ] natural river data does not fabricate canals
[ ] CRS/no-data checks pass
```

## LDD

```text
[ ] point query returns soil/land-use fields
[ ] source CRS normalized
[ ] missing query != zero runoff
```

---

# 27. REGRESSION FIXTURE FORMAT

```text
tests/regression/ban_phaeo/
tests/regression/mae_sai/
tests/regression/nan/
tests/regression/ubon/
tests/regression/hat_yai/
```

Each:

```text
manifest.yaml
observations.jsonl
warnings.json
network.geojson
boundaries.json
controls.json
expected.json
```

## Ban Phaeo invariants

```text
Mae Klong release != direct Damnoen Qin
stale Ban Phaeo H != current
bank ~0.96 MSL only with source/time/spatial scope
unknown pump/gate expands uncertainty
sea tide routes through Tha Chin boundary
no storage-stage => peak_height eligible=false
```

## Mae Sai

```text
STN0029 warning raises public warning floor
warning != H/Q forcing
catchment extends into Myanmar
missing cross-border gauges reduces confidence
global precip may fill context
point depth remains gated
```

## Nan

```text
flash wave -> river wave handoff
event survives local upstream fall
downstream wave remains active
capacity modifier supports debris/blockage
```

## Ubon

```text
bank reference versioned
floodplain storage memory/hysteresis
same H rising/falling may differ spatially
Mekong can be downstream boundary
missing flash product != zero risk
```

## Hat Yai

```text
multiple Qin paths
design capacity != effective capacity
lake/sea may constrain Qout
temporary fall doesn't delete later wave
compound interaction retained
```

---

# 28. FORECAST PROVENANCE

Every forecast run records:

```text
source_id
record/version
observed_at
received_at
quality_state
semantic_status
datum
unit
```

Assumptions:

```text
pump_state_estimated
gate_state_unknown
tide_prediction_only
terrain_tier
network_confidence
bank_reference_id
storage_stage_method
```

---

# 29. ELIGIBILITY MINIMUMS

Occurrence:
- observed impact, or
- official warning + physical evidence, or
- calibrated probability.

Arrival:
- identifiable wave/event;
- connected path;
- travel-time model;
- enough upstream state.

Bankfull ETA:
- valid current/reconstructed H;
- valid spatial bank reference;
- eligible H trajectory.

Peak:
- eligible H forecast;
- valid bank;
- storage-stage/transfer;
- controls/boundary uncertainty within allowed limit.

Point depth:
- exposure eligible;
- T1/T2 or separately validated T3;
- hydraulic connectivity;
- no unresolved major barrier uncertainty.

---

# 30. AUTH / LICENSE GATES

Credentials expected externally:

```text
GISTDA API account/key
NASA PPS/IMERG account/auth if required by route
future authenticated providers
```

HII water-level catalog currently reports:
```text
Creative Commons Attribution Non-Commercial
```

Therefore commercial/monetized production requires license review.

This is a deployment governance blocker, not a reason to redesign the model.

---

# 31. BOOTSTRAP COMMANDS

Work should implement equivalent commands:

```bash
docker compose up -d db
python -m app.db.migrate

python -m app.seed.sources
python -m app.seed.stations

python -m scripts.bootstrap_terrain --region asia --resolution 3s
python -m scripts.bootstrap_hydrobasins --region asia
python -m scripts.bootstrap_hydrorivers --region asia

python -m scripts.check_sources

python -m scripts.ingest_rid
python -m scripts.ingest_navy_tide --year 2026
python -m scripts.ingest_hii_metadata
python -m scripts.ingest_dwr_warnings

pytest tests/regression -q
```

A not-configured optional connector must not stop unrelated bootstrap.

---

# 32. READINESS LEVELS

```text
DATA_PLATFORM_READY
MAP_READY
HAZARD_ONLY_READY
QUANT_FORECAST_PARTIAL
QUANT_FORECAST_READY
POINT_DEPTH_READY
```

Expected after Phase 1/2:

```text
DATA_PLATFORM_READY=true
MAP_READY=true after GIS import
HAZARD_ONLY_READY=true once minimum live sources work
QUANT_FORECAST_PARTIAL=per basin/output
POINT_DEPTH_READY=false nationwide by default
```

Do not call the whole app unusable just because exact depth is unavailable.

---

# 33. MINIMUM PHASE-2 LIVE SET

Target:

```text
one fresh/usable H or warning pathway
+ rainfall pathway
+ official warning pathway
+ HydroBASINS/HydroRIVERS/HydroSHEDS
+ Navy tide for coastal cases
+ RID reservoir state
```

Missing GISTDA/IMERG credentials must not block non-dependent areas/features.

---

# 34. REQUIRED WORK OUTPUT NOW

With this manifest + Master Spec, Work must implement:

1. PostGIS bootstrap.
2. Concrete migrations/schema.
3. Source registry + source health.
4. HII archive/legacy connector with strict station-ID validation.
5. DWR EWS connector.
6. TMD discovery/QPE connector.
7. RID reservoir connector with inflow/outflow physics lockout.
8. Navy tide discovery/PDF parsing pipeline.
9. GISTDA key-gated connector.
10. IMERG auth-gated connector.
11. HydroSHEDS/HydroBASINS/HydroRIVERS bootstrap.
12. LDD soil/land-use connector.
13. Station seeds/mapping verification.
14. Five regression fixtures.
15. `/v1/data-quality` and readiness output.
16. Graceful eligibility instead of placeholders pretending to be forecasts.

Work no longer needs to make logic or UX decisions.

---

# 35. EXTERNAL BLOCKERS THAT ARE NOT DESIGN GAPS

```text
GISTDA actual key/base after account creation
NASA/PPS auth if required
high-resolution local DEM for exact depth everywhere
nationwide realtime pump/gate feeds
verified actual-Q semantics for some controls
RID inflow/outflow units until independently confirmed
commercial source licensing/permissions
```

Implement around them. Do not stop the whole app.

---

# 36. REFERENCE URL LIST

```text
HII catalog
https://data.go.th/th/dataset/water-level

HII legacy daily
https://tiwrm.hii.or.th/DATA/REPORT/php/show_itcwater.php?sdate={YYYY-MM-DD}

HII legacy graph
https://tiwrm.hii.or.th/DATA/REPORT/php/itc_graph2.php?id1={legacy_id}%2C

HII public warning
https://tiwrm.hii.or.th/thaiwater_l5/public/telemetering/wl/warning

DWR warning
https://ews.dwr.go.th/ews/warn_list.php

DWR station
https://ews.dwr.go.th/ews/list_temp.php?link={station_code}

DWR southwest
https://tele-southwest.dwr.go.th/home/Index_HOME

TMD radar discovery
https://weather.tmd.go.th/chn.php

RID dams
https://app.rid.go.th/reservoir/api/dam/public

RID medium reservoirs
https://app.rid.go.th/reservoir/api/reservoir/public

Navy tide
https://hydro.navy.mi.th/waterlaveltable

GISTDA docs
https://disaster.gistda.or.th/services/open-api

HydroSHEDS
https://www.hydrosheds.org/hydrosheds-core-downloads

HydroBASINS
https://www.hydrosheds.org/products/hydrobasins

HydroRIVERS
https://www.hydrosheds.org/products/hydrorivers

NASA IMERG
https://gpm.nasa.gov/data/imerg

IMERG GIS
https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/

LDD land-use/soil
https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_QUERY_WM/MapServer/5

LDD subbasin
https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_QUERY_WM/MapServer/8

LDD soil query
https://eis.ldd.go.th/ArcGIS/rest/services/LDD_SOIL_WM/FeatureServer/6/query
```

---

# 37. FINAL IMPLEMENTATION INSTRUCTION

This manifest exists so Work must **not** respond that the project lacks endpoint/schema/PostGIS/terrain/station definitions and therefore can only show placeholders.

After receiving both files:

```text
thailand_flood_intelligence_master_implementation_spec.md
thailand_flood_intelligence_implementation_data_manifest.md
```

Work must proceed with engineering.

Where credentials/data are truly external, only that connector/capability becomes `NOT_CONFIGURED` or ineligible.

**Do not reopen architecture, hydrologic logic, or UX/UI. Write the code.**

---

**END — IMPLEMENTATION DATA MANIFEST v1**
