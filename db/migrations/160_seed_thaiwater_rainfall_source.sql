INSERT INTO source_registry (
  source_id, provider, dataset, endpoint_type, base_url, native_unit, native_timezone,
  semantics_status, commercial_use_status, expected_update_pattern, priority,
  fallback_group, auth_required, parser_version, enabled, notes
) VALUES (
  'thaiwater_rain_24h', 'ThaiWater', 'Public station rainfall, one and 24 hours',
  'JSON', 'https://api-v3.thaiwater.net', 'mm', NULL, 'PARTIAL',
  'REVIEW_REQUIRED', 'station observations / published 24-hour accumulation', 20,
  'rain', false, '1', true,
  'Rain is reported at stations. Timestamp timezone, 24-hour accumulation semantics, and local trigger thresholds remain unverified.'
)
ON CONFLICT (source_id) DO UPDATE SET
  provider=EXCLUDED.provider,
  dataset=EXCLUDED.dataset,
  endpoint_type=EXCLUDED.endpoint_type,
  base_url=EXCLUDED.base_url,
  native_unit=EXCLUDED.native_unit,
  native_timezone=EXCLUDED.native_timezone,
  semantics_status=EXCLUDED.semantics_status,
  commercial_use_status=EXCLUDED.commercial_use_status,
  expected_update_pattern=EXCLUDED.expected_update_pattern,
  priority=EXCLUDED.priority,
  fallback_group=EXCLUDED.fallback_group,
  auth_required=EXCLUDED.auth_required,
  parser_version=EXCLUDED.parser_version,
  enabled=EXCLUDED.enabled,
  notes=EXCLUDED.notes,
  updated_at=now();
