-- Frozen schema from thailand_flood_intelligence_implementation_data_manifest.md
CREATE INDEX idx_basins_geom ON basins USING gist(geom);
CREATE INDEX idx_catchments_geom ON catchments USING gist(geom);
CREATE INDEX idx_network_nodes_geom ON network_nodes USING gist(geom);
CREATE INDEX idx_network_edges_geom ON network_edges USING gist(geom);
CREATE INDEX idx_stations_geom ON stations USING gist(geom);
CREATE INDEX idx_bank_reference_geom ON bank_references USING gist(representative_geom);
CREATE INDEX idx_storage_geom ON storage_nodes USING gist(geom);
CREATE INDEX idx_warning_geom ON official_warnings USING gist(geom);
CREATE INDEX idx_flood_extent_geom ON flood_extents USING gist(geom);
CREATE INDEX idx_location_exposure_geom ON location_exposure USING gist(location_geom);
CREATE UNIQUE INDEX idx_terrain_products_name_uri ON terrain_products(name,uri);

CREATE INDEX idx_observations_entity_var_time
  ON observations(entity_type,entity_id,variable,observed_at DESC);
CREATE INDEX idx_observations_source_time
  ON observations(source_id,observed_at DESC);
CREATE UNIQUE INDEX idx_observations_deduplicate
  ON observations(source_id,source_record_id,variable,observed_at)
  WHERE source_record_id IS NOT NULL;
CREATE INDEX idx_control_state_time
  ON control_state(control_type,control_id,observed_at DESC);
CREATE INDEX idx_boundary_state_time
  ON boundary_state(boundary_id,observed_at DESC);
CREATE INDEX idx_event_waves_event_state
  ON event_waves(event_id,state);
CREATE INDEX idx_forecast_outputs_target
  ON forecast_outputs(target_type,target_id,variable,valid_at);
CREATE UNIQUE INDEX idx_official_warnings_provider_id
  ON official_warnings(source_id,provider_warning_id)
  WHERE provider_warning_id IS NOT NULL;
