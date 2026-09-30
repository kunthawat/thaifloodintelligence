-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
CREATE TABLE hydrologic_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_name text,
  dominant_hazard hazard_type,
  state event_state NOT NULL,
  origin_catchment_id text REFERENCES catchments(catchment_id),
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  official_warning_present boolean NOT NULL DEFAULT false,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE event_waves (
  wave_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES hydrologic_events(event_id),
  parent_wave_id uuid REFERENCES event_waves(wave_id),
  state wave_state NOT NULL,
  origin_catchment_id text REFERENCES catchments(catchment_id),
  current_edge_id uuid REFERENCES network_edges(edge_id),
  generated_at timestamptz,
  eta_start timestamptz,
  eta_p50 timestamptz,
  eta_end timestamptz,
  peak_q_p10 double precision,
  peak_q_p50 double precision,
  peak_q_p90 double precision,
  confidence double precision,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE runoff_pulses (
  runoff_pulse_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid REFERENCES hydrologic_events(event_id),
  wave_id uuid REFERENCES event_waves(wave_id),
  catchment_id text NOT NULL REFERENCES catchments(catchment_id),
  valid_from timestamptz NOT NULL,
  valid_to timestamptz NOT NULL,
  runoff_volume_m3 double precision,
  q_series jsonb,
  method text NOT NULL,
  confidence double precision,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
