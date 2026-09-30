INSERT INTO stations (canonical_code,canonical_name_th,river_or_waterway,province,district,active,properties)
VALUES
('BP-BAN-PHAEO','บ้านแพ้ว','คลองดำเนินสะดวก','สมุทรสาคร','บ้านแพ้ว',true,
 '{"known_bank_reference":{"value_m":0.96,"datum":"MSL","type":"OFFICIAL_STATION_BANK","status":"REQUIRES_RUNTIME_RECONFIRMATION"},"notes":"Do not use stale 2026-09-26 H≈0.70 m as current."}'::jsonb),
('MK03','ปตร.บางนกแขวก','คลองดำเนินสะดวก/แม่กลอง',NULL,NULL,true,
 '{"candidate_provider_ids":["534","1113"],"notes":"Conflicting legacy IDs; verify returned station code/name before persisting a provider ID."}'::jsonb),
('K.57','บางคนที','แม่น้ำแม่กลอง',NULL,NULL,true,'{}'::jsonb),
('K.58A','บ้านเขาพัง','แควน้อย',NULL,NULL,true,'{}'::jsonb),
('TC.9','วัดท่ากระบือ','แม่น้ำท่าจีน','สมุทรสาคร',NULL,true,'{}'::jsonb),
('STN0029','สถานี EWS แม่สาย',NULL,'เชียงราย','แม่สาย',true,'{}'::jsonb),
('NAN001','NAN001','ลุ่มน้ำน่าน',NULL,NULL,true,'{}'::jsonb),
('NAN002','NAN002','ลุ่มน้ำน่าน',NULL,NULL,true,'{}'::jsonb),
('NAN003','NAN003','ลุ่มน้ำน่าน',NULL,NULL,true,'{}'::jsonb),
('NAN009','NAN009','ลุ่มน้ำน่าน',NULL,NULL,true,'{}'::jsonb),
('M.7','M.7 อุบลราชธานี','แม่น้ำมูล','อุบลราชธานี',NULL,true,
 '{"notes":"Bank/critical reference must be versioned; published values differ by date/source."}'::jsonb),
('X.44','X.44 บ้านหาดใหญ่','คลองอู่ตะเภา','สงขลา',NULL,true,'{}'::jsonb)
ON CONFLICT (canonical_code) DO UPDATE SET
  canonical_name_th=EXCLUDED.canonical_name_th, river_or_waterway=EXCLUDED.river_or_waterway,
  province=EXCLUDED.province, district=EXCLUDED.district, properties=EXCLUDED.properties;

CREATE UNIQUE INDEX IF NOT EXISTS idx_station_source_map_identity
  ON station_source_map(station_id,source_id,COALESCE(provider_station_code,''),COALESCE(provider_station_id,''));

INSERT INTO station_source_map (station_id,source_id,provider_station_code,provider_station_id,mapping_status,verification_method,notes)
SELECT s.station_id, v.source_id, v.provider_station_code, v.provider_station_id, v.mapping_status, v.verification_method, v.notes
FROM (VALUES
 ('BP-BAN-PHAEO','hii_catalog',NULL::text,NULL::text,'VERIFIED_NAME_ONLY','manifest seed; name only','Bank reference requires runtime reconfirmation'),
 ('MK03','hii_legacy_graph','MK03',NULL::text,'CONFLICT','manifest seed','candidate numeric IDs 534 and 1113 are not persisted'),
 ('K.57','hii_legacy_graph','K.57',NULL::text,'CANDIDATE_REQUIRES_NAME_MATCH','manifest candidate','candidate ID 1116 requires exact returned identity'),
 ('K.58A','hii_legacy_graph','K.58A',NULL::text,'CANDIDATE_REQUIRES_NAME_MATCH','manifest candidate','candidate ID 1027 requires exact returned identity'),
 ('TC.9','hii_legacy_graph','TC.9',NULL::text,'CANDIDATE_REQUIRES_NAME_MATCH','manifest candidate','candidate ID 1112 requires exact returned identity'),
 ('STN0029','dwr_ews_station','STN0029',NULL::text,'VERIFIED','manifest verified code',''),
 ('NAN001','hii_catalog','NAN001',NULL::text,'VERIFIED','manifest verified code',''),
 ('NAN002','hii_catalog','NAN002',NULL::text,'VERIFIED','manifest verified code',''),
 ('NAN003','hii_catalog','NAN003',NULL::text,'VERIFIED','manifest verified code',''),
 ('NAN009','hii_catalog','NAN009',NULL::text,'VERIFIED','manifest verified code','')
) AS v(canonical_code,source_id,provider_station_code,provider_station_id,mapping_status,verification_method,notes)
JOIN stations s ON s.canonical_code=v.canonical_code
ON CONFLICT DO NOTHING;
