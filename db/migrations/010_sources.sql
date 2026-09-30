-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
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
