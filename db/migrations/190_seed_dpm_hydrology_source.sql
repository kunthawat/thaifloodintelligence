INSERT INTO source_registry (
  source_id,provider,dataset,endpoint_type,base_url,native_timezone,
  semantics_status,commercial_use_status,expected_update_pattern,
  priority,fallback_group,auth_required,parser_version,enabled,notes
) VALUES (
  'dpm_hydrology','Department of Disaster Prevention and Mitigation',
  'Main/secondary waterways and 22 major basins','ARCGIS REST',
  'https://gis-portal.disaster.go.th/arcgis/rest/services/MapDX/DPM_TH_Hydrology/FeatureServer',
  'Asia/Bangkok','VERIFIED','REVIEW_REQUIRED','static/reference',25,'network_reference',false,'1',true,
  'Layers 4/5 improve local waterway geometry/name coverage. They are REFERENCE_ONLY; HydroRIVERS NEXT_DOWN remains the directional natural-river topology.'
)
ON CONFLICT(source_id) DO UPDATE SET
  provider=EXCLUDED.provider,dataset=EXCLUDED.dataset,endpoint_type=EXCLUDED.endpoint_type,
  base_url=EXCLUDED.base_url,native_timezone=EXCLUDED.native_timezone,
  semantics_status=EXCLUDED.semantics_status,priority=EXCLUDED.priority,
  fallback_group=EXCLUDED.fallback_group,enabled=EXCLUDED.enabled,
  notes=EXCLUDED.notes,updated_at=now();
