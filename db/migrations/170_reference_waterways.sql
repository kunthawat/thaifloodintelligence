-- DPM hydrology is a reference geometry/name layer.  It must never invent direction.
CREATE TABLE IF NOT EXISTS reference_waterways (
  waterway_id text PRIMARY KEY,
  source_id text NOT NULL,
  source_layer integer NOT NULL,
  waterway_class text NOT NULL,
  name_th text,
  name_en text,
  main_river_name_th text,
  geom geometry(MultiLineString,4326) NOT NULL,
  topology_role text NOT NULL DEFAULT 'REFERENCE_ONLY',
  properties jsonb NOT NULL DEFAULT '{}'::jsonb,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reference_waterways_geom_gix ON reference_waterways USING gist(geom);
CREATE INDEX IF NOT EXISTS reference_waterways_name_idx ON reference_waterways(name_th,main_river_name_th);

CREATE TABLE IF NOT EXISTS dpm_major_basins (
  basin_code text PRIMARY KEY,
  name_th text NOT NULL,
  name_en text,
  area_km2 double precision,
  geom geometry(MultiPolygon,4326) NOT NULL,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dpm_major_basins_geom_gix ON dpm_major_basins USING gist(geom);
