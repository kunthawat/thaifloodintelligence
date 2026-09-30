import json
from pathlib import Path
import unittest


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class FrozenArchetypeFixtures(unittest.TestCase):
    def test_five_frozen_scenarios_are_documented_without_fabricated_observations(self):
        expected = {"ban_phaeo", "mae_sai", "nan", "ubon", "hat_yai"}
        actual = {path.stem for path in FIXTURE_DIR.glob("*.json")}
        self.assertEqual(actual, expected)
        for path in FIXTURE_DIR.glob("*.json"):
            with self.subTest(archetype=path.stem):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsNone(fixture["available_observations"])
                self.assertTrue(fixture["expected_properties"])
                self.assertEqual(fixture["status"], "STRUCTURAL_REGRESSION_FIXTURE_NO_LIVE_DATA")


if __name__ == "__main__":
    unittest.main()
