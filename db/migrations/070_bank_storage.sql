-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
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
