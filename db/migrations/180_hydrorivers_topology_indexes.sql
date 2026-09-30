-- Expression indexes support deterministic NEXT_DOWN traversal.
CREATE INDEX IF NOT EXISTS idx_network_edges_hyriv_id
  ON network_edges ((properties->'source_fields'->>'HYRIV_ID'))
  WHERE properties->>'source'='HydroRIVERS';
CREATE INDEX IF NOT EXISTS idx_network_edges_next_down_provider
  ON network_edges ((properties->>'next_down_provider_id'))
  WHERE properties->>'source'='HydroRIVERS';
CREATE INDEX IF NOT EXISTS idx_network_edges_main_riv
  ON network_edges ((properties->'source_fields'->>'MAIN_RIV'))
  WHERE properties->>'source'='HydroRIVERS';
