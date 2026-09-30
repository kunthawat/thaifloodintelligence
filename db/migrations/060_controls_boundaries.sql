-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
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
