import unittest

from app.hydrology.controls import effective_capacity
from app.hydrology.boundaries import TideComponents, gate_downstream_stage
from app.hydrology.eligibility import peak_height_eligibility
from app.hydrology.events import EventState, HydrologicEvent
from app.hydrology.floodplain import FloodplainState, next_floodplain_state
from app.hydrology.graph import (
    EdgeDirection, EdgeType, EffectiveDirection, FlowEvidence, GraphEdge, effective_direction,
)
from app.hydrology.routing import TravelTimeDistribution
from app.hydrology.runoff import RunoffInput, effective_rainfall
from app.hydrology.storage import mass_balance_step, stage_from_storage


class HydrologyGuardrailTests(unittest.TestCase):
    def test_second_wave_prevents_event_termination_while_local_level_falls(self):
        event = HydrologicEvent("event-1", EventState.RECESSION, 0, 1, False, True, ["wave-1", "wave-2"])
        self.assertFalse(event.can_end())
        self.assertEqual(event.refresh_terminal_state(), EventState.RECESSION)

    def test_unknown_control_state_is_not_zero_or_full_capacity(self):
        result = effective_capacity(100.0, None, 1.0, 1.0, 1.0, semantics_verified=True, capacity_unit="m3/s")
        self.assertFalse(result.eligible)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, "CONTROL_STATE_TOO_UNCERTAIN")

    def test_closed_gate_blocks_flow_and_unknown_gate_stays_unknown(self):
        edge = GraphEdge("canal", "upstream", "downstream", EdgeType.GATE_PATH, EdgeDirection.CONTROLLED)
        closed = effective_direction(edge, FlowEvidence(semantics_verified=True, gate_state="CLOSED"))
        unknown = effective_direction(edge, FlowEvidence(semantics_verified=True))
        self.assertEqual(closed, EffectiveDirection.BLOCKED)
        self.assertEqual(unknown, EffectiveDirection.UNKNOWN)

    def test_dynamic_canal_can_reverse_only_with_fresh_comparable_stages(self):
        edge = GraphEdge("canal", "upstream", "downstream", EdgeType.CONTROLLED_CANAL, EdgeDirection.DYNAMIC)
        evidence = FlowEvidence(
            upstream_stage=0.9, downstream_stage=1.3, stages_share_datum=True,
            stages_fresh=True, semantics_verified=True, gate_state="OPEN",
        )
        self.assertEqual(effective_direction(edge, evidence), EffectiveDirection.REVERSE)
        evidence = FlowEvidence(
            upstream_stage=0.9, downstream_stage=1.3, stages_share_datum=False,
            stages_fresh=True, semantics_verified=True, gate_state="OPEN",
        )
        self.assertEqual(effective_direction(edge, evidence), EffectiveDirection.UNKNOWN)

    def test_stage_storage_model_is_required_for_quantitative_stage(self):
        stage, reason = stage_from_storage(120.0, [(100.0, 2.0), (200.0, 3.0)], curve_validated=False, datum="MSL")
        self.assertIsNone(stage)
        self.assertEqual(reason, "NO_VALID_STAGE_STORAGE_MODEL")
        stage, reason = stage_from_storage(150.0, [(100.0, 2.0), (200.0, 3.0)], curve_validated=True, datum="MSL")
        self.assertEqual(stage, 2.5)
        self.assertIsNone(reason)

    def test_mass_balance_does_not_directly_produce_stage(self):
        result = mass_balance_step(
            storage_m3=1000, qin_m3s=12, qout_m3s=9, timestep_seconds=60, inputs_verified=True,
        )
        self.assertEqual(result.storage_next_m3, 1180)
        self.assertFalse(hasattr(result, "stage"))

    def test_peak_height_requires_all_physical_inputs(self):
        eligible, reason = peak_height_eligibility(
            current_stage_fresh=True, bank_reference_available=True, bank_reference_in_scope=True, stage_storage_valid=False,
            controls_sufficiently_known=True, boundary_sufficiently_known=True,
        )
        self.assertFalse(eligible)
        self.assertEqual(reason, "NO_VALID_STAGE_STORAGE_MODEL")

    def test_unvalidated_rain_loss_does_not_create_runoff_value(self):
        result = effective_rainfall(RunoffInput(30, "mm", 10, "mm", True, True, False))
        self.assertFalse(result.eligible)
        self.assertIsNone(result.effective_rainfall)

    def test_missing_calibration_does_not_create_fixed_travel_time(self):
        result = TravelTimeDistribution(3600, 7200, 10800, 0, False, "UNVALIDATED")
        self.assertFalse(result.eligible)
        self.assertEqual(result.reason, "INSUFFICIENT_CALIBRATION")

    def test_floodplain_hysteresis_keeps_connected_water_during_recession(self):
        state = next_floodplain_state(
            FloodplainState.CONNECTED, channel_overflowing=False,
            hydraulic_connection=True, water_remains=True, level_falling=True,
        )
        self.assertEqual(state, FloodplainState.DRAINING)
        isolated = next_floodplain_state(
            state, channel_overflowing=False, hydraulic_connection=False,
            water_remains=True, level_falling=True,
        )
        self.assertEqual(isolated, FloodplainState.ISOLATED_PONDING)

    def test_sea_tide_is_not_used_as_inland_gate_stage_without_propagation(self):
        tide = TideComponents(1.2, None, None, "m", "MSL", "2026-09-29T00:00:00+00:00", True, True, True)
        result = gate_downstream_stage(
            tide, river_path_id="estuary-path", propagation_model=None,
            expected_unit="m", expected_datum="MSL",
        )
        self.assertFalse(result.eligible)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, "DOWNSTREAM_BOUNDARY_UNCERTAIN")

    def test_official_warning_contract_does_not_enter_hydraulic_forecast(self):
        from app.models.forecast import build_forecast
        forecast = build_forecast({"latitude": 14.0, "longitude": 101.0})
        self.assertIsNone(forecast["overall_probability"])
        self.assertFalse(forecast["occurrence"]["eligible"])
        self.assertNotIn("official_warning_forcing", forecast)

    def test_cross_border_catchment_is_representable_without_country_clipping(self):
        from app.hydrology.catchment import CatchmentAttributes
        catchment = CatchmentAttributes("mae-sai-upstream", contributing_countries=("TH", "MM"))
        self.assertEqual(catchment.contributing_countries, ("TH", "MM"))


if __name__ == "__main__":
    unittest.main()
