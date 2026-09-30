-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
CREATE TABLE forecast_runs (
  forecast_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_version text NOT NULL,
  generated_at timestamptz NOT NULL DEFAULT now(),
  forecast_origin timestamptz NOT NULL,
  horizon_end timestamptz NOT NULL,
  event_id uuid REFERENCES hydrologic_events(event_id),
  status text NOT NULL,
  input_snapshot jsonb NOT NULL,
  source_health_snapshot jsonb NOT NULL,
  assumptions jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE forecast_members (
  forecast_member_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  forecast_run_id uuid NOT NULL REFERENCES forecast_runs(forecast_run_id),
  member_no integer NOT NULL,
  scenario_weight double precision NOT NULL DEFAULT 1.0,
  scenario_inputs jsonb NOT NULL,
  UNIQUE(forecast_run_id,member_no)
);

CREATE TABLE forecast_outputs (
  forecast_output_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  forecast_run_id uuid NOT NULL REFERENCES forecast_runs(forecast_run_id),
  target_type text NOT NULL,
  target_id text NOT NULL,
  variable text NOT NULL,
  valid_at timestamptz,
  p10 double precision,
  p50 double precision,
  p90 double precision,
  probability double precision,
  unit text,
  datum text,
  eligible boolean NOT NULL,
  eligibility_reason text,
  confidence confidence_level NOT NULL,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
