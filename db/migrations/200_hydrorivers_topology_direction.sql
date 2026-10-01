-- HydroRIVERS NEXT_DOWN defines source topology direction.
-- This does NOT verify realtime hydraulic direction or controlled-canal behavior.
UPDATE network_edges
SET direction_type='FORWARD',
    properties = properties || jsonb_build_object(
      'topology_direction_verified', true,
      'realtime_hydraulic_direction_verified', false
    )
WHERE properties->>'source'='HydroRIVERS'
  AND properties ? 'next_down_provider_id';
