"""Structural checks for the manifest's migration and mapping safeguards."""

from pathlib import Path
import unittest
import json


ROOT = Path(__file__).parents[1]


class ManifestDatabaseTests(unittest.TestCase):
    def test_migrations_follow_manifest_order(self):
        actual = [path.name for path in sorted((ROOT / "db" / "migrations").glob("*.sql"))]
        frozen_core = [
            "001_types.sql", "010_sources.sql", "020_geography.sql", "030_network.sql",
            "040_stations.sql", "050_observations.sql", "060_controls_boundaries.sql",
            "070_bank_storage.sql", "080_events.sql", "090_forecasts.sql",
            "100_warnings_impacts.sql", "110_indexes.sql", "120_seed_sources.sql", "130_seed_stations.sql",
        ]
        self.assertEqual(actual[:len(frozen_core)], frozen_core)
        numeric_prefixes = [int(name.split("_", 1)[0]) for name in actual]
        self.assertEqual(numeric_prefixes, sorted(numeric_prefixes))
        self.assertEqual(len(numeric_prefixes), len(set(numeric_prefixes)))

    def test_observations_partition_and_source_warnings_are_deduplicated(self):
        observation = (ROOT / "db" / "migrations" / "050_observations.sql").read_text(encoding="utf-8")
        indexes = (ROOT / "db" / "migrations" / "110_indexes.sql").read_text(encoding="utf-8")
        self.assertIn("PARTITION BY RANGE (observed_at)", observation)
        self.assertIn("PARTITION OF observations DEFAULT", observation)
        self.assertIn("idx_observations_deduplicate", indexes)
        self.assertIn("idx_official_warnings_provider_id", indexes)

    def test_candidate_numeric_ids_are_not_persisted_as_verified_station_ids(self):
        seeds = (ROOT / "db" / "migrations" / "130_seed_stations.sql").read_text(encoding="utf-8")
        for candidate in ("1116", "1027", "1112", "534", "1113"):
            self.assertIn(candidate, seeds)
        self.assertIn("candidate ID 1116 requires exact returned identity", seeds)
        candidate_rows = seeds.split("INSERT INTO station_source_map", 1)[1]
        self.assertNotIn("'1116'", candidate_rows)
        self.assertNotIn("'1027'", candidate_rows)

    def test_regression_archives_use_full_manifest_shape_without_fake_data(self):
        regression_root = ROOT / "tests" / "regression"
        for name in ("ban_phaeo", "mae_sai", "nan", "ubon", "hat_yai"):
            with self.subTest(archetype=name):
                folder = regression_root / name
                self.assertEqual(
                    {path.name for path in folder.iterdir()},
                    {"manifest.yaml", "observations.jsonl", "warnings.json", "network.geojson", "boundaries.json", "controls.json", "expected.json"},
                )
                self.assertEqual((folder / "observations.jsonl").read_bytes(), b"")
                self.assertEqual(json.loads((folder / "network.geojson").read_text(encoding="utf-8"))["features"], [])
                warning = json.loads((folder / "warnings.json").read_text(encoding="utf-8"))
                self.assertFalse(warning["empty_means_no_warning"])
                expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
                self.assertEqual(expected["status"], "STRUCTURAL_ONLY_NO_VERIFIED_FIELD_DATA")


if __name__ == "__main__":
    unittest.main()
