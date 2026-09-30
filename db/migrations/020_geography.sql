-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
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
