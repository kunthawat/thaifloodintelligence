-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
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
ALTER TABLE observation_quality
  ADD CONSTRAINT observation_quality_observation_fk
  FOREIGN KEY (observation_id,observed_at)
  REFERENCES observations(observation_id,observed_at);
