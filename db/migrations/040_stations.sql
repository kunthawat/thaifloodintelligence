-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
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
