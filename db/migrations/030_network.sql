-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
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
