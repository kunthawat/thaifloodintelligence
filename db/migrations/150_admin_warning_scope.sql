-- Administrative geometry for resolving textual official-warning scope.
CREATE TABLE IF NOT EXISTS admin_province (
  prov_code text PRIMARY KEY,
  prov_name_th text NOT NULL,
  geom geometry(MultiPolygon,4326) NOT NULL,
  source_url text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS admin_province_geom_gix ON admin_province USING gist (geom);

CREATE TABLE IF NOT EXISTS admin_amphoe (
  amp_code text PRIMARY KEY,
  prov_code text NOT NULL,
  prov_name_th text NOT NULL,
  amp_name_th text NOT NULL,
  geom geometry(MultiPolygon,4326) NOT NULL,
  source_url text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS admin_amphoe_geom_gix ON admin_amphoe USING gist (geom);
CREATE INDEX IF NOT EXISTS admin_amphoe_name_idx ON admin_amphoe (prov_name_th,amp_name_th);

CREATE TABLE IF NOT EXISTS admin_tambon (
  tam_code text PRIMARY KEY,
  amp_code text NOT NULL,
  prov_code text NOT NULL,
  prov_name_th text NOT NULL,
  amp_name_th text NOT NULL,
  tam_name_th text NOT NULL,
  geom geometry(MultiPolygon,4326) NOT NULL,
  source_url text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS admin_tambon_geom_gix ON admin_tambon USING gist (geom);
CREATE INDEX IF NOT EXISTS admin_tambon_name_idx ON admin_tambon (prov_name_th,amp_name_th,tam_name_th);

ALTER TABLE official_warnings ADD COLUMN IF NOT EXISTS scope_method text;
ALTER TABLE official_warnings ADD COLUMN IF NOT EXISTS scope_confidence double precision;
ALTER TABLE official_warnings ADD COLUMN IF NOT EXISTS admin_level text;
ALTER TABLE official_warnings ADD COLUMN IF NOT EXISTS admin_code text;
ALTER TABLE official_warnings ADD COLUMN IF NOT EXISTS scope_text_normalized text;
CREATE UNIQUE INDEX IF NOT EXISTS official_warning_provider_uidx
  ON official_warnings(source_id,provider_warning_id) WHERE provider_warning_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS official_warnings_geom_gix ON official_warnings USING gist (geom);
