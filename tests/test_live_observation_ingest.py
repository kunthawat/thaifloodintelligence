from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.live_observation_ingest import _observed_at, _rain_rows, _stage_rows
from app.services.waterlevel_live import _normalize


class LiveObservationIngestTests(unittest.TestCase):
    def test_naive_thaiwater_time_is_normalized_but_assumption_is_preserved(self):
        now_th = datetime.now(ZoneInfo("Asia/Bangkok")).replace(microsecond=0)
        parsed, reasons = _observed_at(now_th.replace(tzinfo=None).isoformat(sep=" "))
        self.assertIsNotNone(parsed)
        self.assertIn("SOURCE_TIMEZONE_ASSUMED_ASIA_BANGKOK", reasons)

    def test_stage_snapshot_becomes_canonical_evidence_candidate_not_physics_forcing(self):
        now_th = datetime.now(ZoneInfo("Asia/Bangkok")).replace(microsecond=0)
        rows = _stage_rows({"stations": [{
            "station_id": "123",
            "station_code": "C.2",
            "lat": 15.0,
            "lon": 100.0,
            "observed_at_source": now_th.replace(tzinfo=None).isoformat(sep=" "),
            "waterlevel_msl_m": 4.2,
            "diff_wl_bank_text": "ต่ำกว่าตลิ่ง (ม.)",
        }]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["variable"], "WATER_LEVEL")
        self.assertEqual(rows[0]["quality_state"], "VALID")
        self.assertFalse(rows[0]["physics_eligible"])
        self.assertEqual(rows[0]["semantic_status"], "VERIFIED")

    def test_rain_snapshot_yields_1h_and_24h_observations(self):
        now_th = datetime.now(ZoneInfo("Asia/Bangkok")).replace(microsecond=0)
        rows = _rain_rows({"stations": [{
            "station_id": "r1",
            "lat": 14.0,
            "lon": 100.0,
            "observed_at_source": now_th.replace(tzinfo=None).isoformat(sep=" "),
            "rain_1h_mm": 2.5,
            "rain_24h_mm": 51.4,
        }]})
        self.assertEqual({row["variable"] for row in rows}, {"RAIN_1H", "RAIN_24H"})
        self.assertTrue(all(row["quality_state"] in {"VALID", "VALID_ZERO"} for row in rows))
        self.assertTrue(all(row["physics_eligible"] is False for row in rows))

    def test_waterlevel_normalizer_preserves_provider_bank_evidence(self):
        payload = {
            "waterlevel_data": {
                "result": "OK",
                "data": [{
                    "station": {
                        "id": 7,
                        "tele_station_lat": "13.7",
                        "tele_station_long": "100.5",
                        "tele_station_name": {"th": "ทดสอบ"},
                        "warning_level_m": "2.0",
                        "critical_level_m": "2.5",
                        "left_bank": "2.8",
                        "right_bank": "2.7",
                        "min_bank": "2.7",
                    },
                    "waterlevel_datetime": "2026-10-01 09:00:00",
                    "waterlevel_msl": "2.9",
                    "waterlevel_m": "3.0",
                    "diff_wl_bank": "0.2",
                    "diff_wl_bank_text": "ล้นตลิ่ง (ม.)",
                    "situation_level": 5,
                    "geocode": {},
                    "agency": {},
                }],
            }
        }
        row = _normalize(payload)[0]
        self.assertEqual(row["min_bank_m"], 2.7)
        self.assertEqual(row["diff_wl_bank_text"], "ล้นตลิ่ง (ม.)")
        self.assertEqual(row["source_situation_level"], 5)


if __name__ == "__main__":
    unittest.main()
