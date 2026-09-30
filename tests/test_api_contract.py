import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_risk_is_unknown_when_sources_are_missing(self):
        response = self.client.get("/v1/location/risk", params={"lat": 13.7, "lon": 100.5})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["risk_level"], "UNKNOWN")
        self.assertIsNone(payload["overall_probability"])
        self.assertEqual(payload["data_state"], "INSUFFICIENT_DATA")

    def test_forecast_preserves_independent_eligibility_and_null_values(self):
        response = self.client.get("/v1/location/forecast", params={"lat": 13.7, "lon": 100.5})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for output in ("first_impact", "time_to_bankfull", "peak_above_bank_m", "time_to_peak", "duration_above_bank", "location_exposure", "point_depth"):
            self.assertFalse(payload[output]["eligible"], output)
            self.assertIsNone(payload[output].get("value", payload[output].get("p50_hours")), output)
            self.assertTrue(payload[output]["reason"], output)

    def test_empty_wave_list_is_marked_unavailable_not_no_waves(self):
        response = self.client.get("/v1/network/waves", params={"lat": 13.7, "lon": 100.5})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["available"])
        self.assertIn("ไม่ได้", payload["detail"])

    def test_official_warning_absence_is_not_implied(self):
        with patch("data.connectors.providers.CONNECTORS", {
            "dwr_ews_warnings": type("Unavailable", (), {"fetch": AsyncMock(side_effect=RuntimeError("offline"))})(),
            "hii_public_warning": type("Unavailable", (), {"fetch": AsyncMock(side_effect=RuntimeError("offline"))})(),
        }):
            response = self.client.get("/v1/official-warnings")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["reason"], "NO_VALID_WARNING_RECORDS")

    def test_public_ui_and_static_assets_are_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/assets/app.css").status_code, 200)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
