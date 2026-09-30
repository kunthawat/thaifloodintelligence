"""Offline acceptance checks for the connector safety contracts."""

from __future__ import annotations

import io
import sys
import types
import unittest
import zipfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from data.connectors.base import HTTPResponse, RawRecord
from data.connectors.providers import (
    CONNECTORS,
    _find_tmd_qpe_href,
    _hii_csv_records,
    _navy_year_links,
    _parse_tide_pdf,
    _validate_qpe_zip,
)


class ManifestConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_hii_archive_is_schema_date_aware_and_keeps_missing_values(self):
        csv_data = (
            "station_code,datetime,water_level\n"
            "NAN001,2026-09-29 07:00:00,-999\n"
            "NAN001,2026-09-29 07:10:00,0\n"
        ).encode()
        records = _hii_csv_records(csv_data, "NAN001.csv", "NAN001", "abc")
        connector = CONNECTORS["hii_catalog"]
        missing = connector.normalize(records[0])[0]
        zero = connector.normalize(records[1])[0]
        self.assertEqual(records[0].payload["parser_version"], "thaiwater.standard")
        self.assertEqual(missing.quality_state, "MISSING")
        self.assertIsNone(missing.value)
        self.assertEqual(zero.quality_state, "VALID_ZERO")
        self.assertEqual(zero.unit, "m")
        self.assertEqual(zero.datum, "MSL")
        self.assertFalse(zero.physics_eligible)  # archived history cannot be live current state

    async def test_hii_legacy_id_must_match_returned_station_identity(self):
        connector = CONNECTORS["hii_legacy_graph"]
        response = HTTPResponse(
            "https://tiwrm.hii.or.th/DATA/REPORT/php/itc_graph2.php?id1=1116%2C",
            200, "text/html",
            b"<b>Station Code: K.57</b><b>Station Name: Bang Khonthi</b>", 1,
        )
        with patch("data.connectors.providers.fetch_https", AsyncMock(return_value=response)):
            records = await connector.fetch_hii_graph("1116", "K.57", "บางคนที")
        self.assertEqual(records, [])
        with patch("data.connectors.providers.fetch_https", AsyncMock(return_value=response)):
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                await connector.fetch_hii_graph("534", "MK03", "ปตร.บางนกแขวก")

    def test_rid_flow_units_stay_null_and_physics_locked(self):
        connector = CONNECTORS["rid_dam"]
        now = datetime.now(timezone.utc).astimezone().isoformat()
        record = RawRecord("rid_dam", "dam-1", {
            "id": "dam-1", "date": now, "storage": 25.4,
            "inflow": 90.0, "outflow": 80.0,
        }, now)
        output = {item.variable: item for item in connector.normalize(record)}
        self.assertEqual(output["RESERVOIR_STORAGE_MCM"].unit, "million m3")
        self.assertEqual(output["RID_RAW_INFLOW"].unit, None)
        self.assertEqual(output["RID_RAW_OUTFLOW"].unit, None)
        self.assertFalse(output["RID_RAW_INFLOW"].physics_eligible)
        self.assertEqual(output["RID_RAW_INFLOW"].semantic_status, "UNVERIFIED")

    def test_tmd_discovery_href_is_dynamic_and_grid_units_remain_unverified(self):
        page = '<a href="../composite/current.asc.zip"><img alt="Nationwide QPE ASCII file"></a>'
        self.assertEqual(
            _find_tmd_qpe_href("https://weather.tmd.go.th/chn.php", page),
            "https://weather.tmd.go.th/composite/current.asc.zip",
        )
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("qpe.asc", "ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n1 2\n3 4\n")
        header = _validate_qpe_zip(stream.getvalue())
        self.assertIsNone(header["units"])
        self.assertEqual(header["units_status"], "UNVERIFIED")

    def test_navy_msl_hour_table_is_parsed_as_local_forecast(self):
        values = " ".join(str(index / 10) for index in range(24))
        sample = (
            "Pak Nam Tha Chin (Samut Sakhon)\n"
            "HEIGHTS OF WATER PREDICTED IN METERS ABOVE MEAN SEA LEVEL\n"
            "January 2026\n"
            f"1 {values}\n"
        )
        fake_reader = types.SimpleNamespace(pages=[types.SimpleNamespace(extract_text=lambda: sample)])
        fake_module = types.SimpleNamespace(PdfReader=lambda _stream: fake_reader)
        with patch.dict(sys.modules, {"pypdf": fake_module}):
            points = _parse_tide_pdf(b"%PDF-test", 2026, "Pak Nam Tha Chin")
        self.assertEqual(len(points), 24)
        self.assertEqual(points[0]["predicted_at"], "2026-01-01T00:00:00+07:00")
        tide = CONNECTORS["navy_tide"].normalize(RawRecord(
            "navy_tide", "row-1", {"station": "Pak Nam Tha Chin", "predicted_level_m": 0.4}, points[0]["predicted_at"]
        ))[0]
        self.assertEqual(tide.observation_type, "FORECAST")
        self.assertEqual(tide.datum, "MSL")
        self.assertFalse(tide.physics_eligible)

    def test_navy_station_download_is_selected_by_current_year_msl_column(self):
        page = """
          <h1>มาตราน้ำในน่านน้ำไทย พ.ศ.2569</h1>
          <table><tr><th>Station</th><th>Lowest Low Water</th><th>Mean Sea Level</th></tr>
          <tr><td>Pak Nam Mae Klong</td><td><a href="MK2026llw.pdf">Download</a></td>
          <td><a href="MK2026mls.pdf">Download</a></td></tr></table>
        """
        selected = _navy_year_links("https://hydro.navy.mi.th/waterlaveltable", page, "2026", "Pak Nam Mae Klong")
        self.assertEqual(len(selected), 1)
        self.assertTrue(selected[0]["url"].endswith("MK2026mls.pdf"))


if __name__ == "__main__":
    unittest.main()
