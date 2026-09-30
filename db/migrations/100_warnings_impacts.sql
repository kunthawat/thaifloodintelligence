-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
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
