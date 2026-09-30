from datetime import datetime, timedelta, timezone
import unittest

from app.services.quality import QualityPolicy, normalize_observation


class ObservationQualityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
        self.policy = QualityPolicy(
            expected_unit="m",
            expected_datum="MSL",
            semantics_status="VERIFIED",
            freshness_warn_after_seconds=600,
            freshness_reject_after_seconds=1800,
        )

    def record(self, value, observed_at=None, **overrides):
        raw = {
            "entity_id": "station-a",
            "variable": "stage",
            "value": value,
            "unit": "m",
            "datum": "MSL",
            "observed_at": observed_at or self.now.isoformat(),
            "received_at": self.now.isoformat(),
            "source_id": "hii",
            "source_record_id": "row-1",
            "observation_type": "OBSERVED",
        }
        raw.update(overrides)
        return normalize_observation(raw, self.policy, now=self.now)

    def test_missing_sentinels_never_become_measurements(self):
        for sentinel in ("-999", "999999", "9999", "-"):
            with self.subTest(sentinel=sentinel):
                observation = self.record(sentinel)
                self.assertIsNone(observation.value)
                self.assertEqual(observation.quality_state, "MISSING")

    def test_non_finite_values_do_not_enter_observations(self):
        for invalid in ("NaN", "Infinity", "-Infinity", True):
            with self.subTest(invalid=invalid):
                observation = self.record(invalid)
                self.assertIsNone(observation.value)
                self.assertEqual(observation.quality_state, "MISSING")

    def test_future_observation_time_is_suspect(self):
        future = (self.now + timedelta(minutes=1)).isoformat()
        observation = self.record(2.4, future)
        self.assertEqual(observation.quality_state, "SUSPECT")
        self.assertIn("FUTURE_OBSERVATION_TIMESTAMP", observation.quality_reasons)

    def test_zero_is_a_valid_observation_when_verified(self):
        observation = self.record(0)
        self.assertEqual(observation.value, 0)
        self.assertEqual(observation.quality_state, "VALID_ZERO")

    def test_stale_stage_is_never_current(self):
        old = (self.now - timedelta(hours=1)).isoformat()
        observation = self.record(2.4, old)
        self.assertEqual(observation.quality_state, "STALE")
        self.assertIn("FRESHNESS_REJECT_THRESHOLD_EXCEEDED", observation.quality_reasons)

    def test_unverified_units_and_semantics_are_suspect(self):
        observation = self.record(2.4, unit="feet")
        self.assertEqual(observation.quality_state, "SUSPECT")
        self.assertIn("UNIT_MISMATCH", observation.quality_reasons)

    def test_naive_timestamp_requires_declared_native_timezone(self):
        raw = {
            "entity_id": "station-a", "variable": "stage", "value": 1.2,
            "unit": "m", "datum": "MSL", "observed_at": "2026-09-29T07:00:00",
            "received_at": self.now.isoformat(), "source_id": "hii", "source_record_id": "row-2",
        }
        unresolved = normalize_observation(raw, self.policy, now=self.now)
        self.assertEqual(unresolved.quality_state, "SUSPECT")
        thai_time = normalize_observation(raw, QualityPolicy(**{**self.policy.__dict__, "native_timezone": "Asia/Bangkok"}), now=self.now)
        self.assertEqual(thai_time.observed_at, self.now.isoformat())
        self.assertEqual(thai_time.quality_state, "VALID")


if __name__ == "__main__":
    unittest.main()
