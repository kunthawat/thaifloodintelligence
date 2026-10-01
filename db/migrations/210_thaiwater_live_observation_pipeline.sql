-- Align the persistent source registry with the runtime ThaiWater live-observation path.
-- ThaiWater remains PARTIAL because timestamp semantics/calibration are not fully frozen;
-- enabling the source does not make it quantitative-model eligible.
UPDATE source_registry
SET dataset='Public water-level station observations',
    native_unit='m',
    native_datum='MSL (waterlevel_msl only)',
    semantics_status='PARTIAL',
    expected_update_pattern='station observations / approximately 10-minute refresh',
    priority=20,
    fallback_group='stage',
    enabled=true,
    notes='Live station observations are persisted to canonical observations. waterlevel_msl is station evidence; location flood inference still requires verified hydraulic linkage/bank scope. Timestamp timezone remains explicitly tracked as an assumption until provider semantics are frozen.',
    updated_at=now()
WHERE source_id='thaiwater_v3';

UPDATE source_registry
SET semantics_status='PARTIAL',
    expected_update_pattern='station observations / published one-hour and 24-hour accumulations',
    enabled=true,
    notes='Live station rainfall is persisted to canonical observations as context/evidence. It is not point rainfall or a calibrated flood trigger; quantitative runoff remains gated.',
    updated_at=now()
WHERE source_id='thaiwater_rain_24h';
