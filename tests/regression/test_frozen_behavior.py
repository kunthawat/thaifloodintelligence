"""Behavior-level guards for the five frozen basin archetypes.

The scenarios carry no measured rainfall, flow, stage, or hazard labels.
"""

import asyncio
from pathlib import Path
import unittest

from app.hydrology.boundaries import TideComponents, gate_downstream_stage
from app.hydrology.catchment import CatchmentAttributes
from app.hydrology.controls import effective_capacity
from app.hydrology.events import EventState, HydrologicEvent
from app.hydrology.floodplain import FloodplainState, next_floodplain_state
from app.hydrology.graph import EdgeDirection, EdgeType, EffectiveDirection, FlowEvidence, GraphEdge, effective_direction
from data.connectors.base import ConnectorNotConfigured
from data.connectors.providers import GLOBAL_PRECIP


class FrozenBasinBehaviorTests(unittest.TestCase):
    def test_ban_phaeo_controlled_canal_may_reverse_and_tide_needs_propagation(self):
        edge = GraphEdge("controlled-canal", "canal-a", "canal-b", EdgeType.GATE_PATH, EdgeDirection.CONTROLLED)
        evidence = FlowEvidence(
            upstream_stage=1.0, downstream_stage=1.2, stages_share_datum=True,
            stages_fresh=True, semantics_verified=True, gate_state="OPEN",
        )
        self.assertEqual(effective_direction(edge, evidence), EffectiveDirection.REVERSE)
        tide = TideComponents(1.1, None, None, "m", "MSL", None, True, True, True)
        inland = gate_downstream_stage(
            tide, river_path_id=None, propagation_model=None,
            expected_unit="m", expected_datum="MSL",
        )
        self.assertFalse(inland.eligible)
        self.assertIsNone(inland.value)

    def test_mae_sai_catchment_keeps_myanmar_contribution_and_names_rain_fallback_blocker(self):
        catchment = CatchmentAttributes("mae-sai", contributing_countries=("TH", "MM"))
        self.assertIn("MM", catchment.contributing_countries)

        async def read_fallback():
            await GLOBAL_PRECIP.fetch()

        with self.assertRaises(ConnectorNotConfigured) as error:
            asyncio.run(read_fallback())
        self.assertEqual(error.exception.blocker.source_id, "global_precip")

    def test_nan_flash_wave_can_continue_into_main_river_after_headwater_falls(self):
        event = HydrologicEvent("nan-cascade", EventState.HEADWATER_ROUTING, 0, 1, False, False, ["flash-wave", "river-wave"])
        event.state = EventState.MAIN_RIVER_ROUTING
        self.assertEqual(event.refresh_terminal_state(), EventState.MAIN_RIVER_ROUTING)
        self.assertFalse(event.can_end())
        self.assertEqual(len(event.waves), 2)

    def test_ubon_floodplain_remains_wet_while_connected_water_recedes(self):
        result = next_floodplain_state(
            FloodplainState.CONNECTED, channel_overflowing=False,
            hydraulic_connection=True, water_remains=True, level_falling=True,
        )
        self.assertEqual(result, FloodplainState.DRAINING)
        still_wet = next_floodplain_state(
            result, channel_overflowing=False, hydraulic_connection=True,
            water_remains=True, level_falling=False,
        )
        self.assertEqual(still_wet, FloodplainState.CONNECTED)
        migration = (Path(__file__).parents[2] / "db" / "migrations" / "070_bank_storage.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE bank_references", migration)
        self.assertIn("valid_from timestamptz", migration)
        self.assertIn("representative_geom geometry", migration)
        self.assertIn("spatial_extent_m double precision", migration)
        stations = (Path(__file__).parents[2] / "config" / "station_seeds.yaml").read_text(encoding="utf-8")
        self.assertIn('status: "REQUIRES_RUNTIME_RECONFIRMATION"', stations)

    def test_hat_yai_unknown_controls_and_second_wave_remain_uncertain(self):
        capacity = effective_capacity(
            100.0, availability=None, head_factor=1.0, blockage_factor=1.0,
            operation_factor=1.0, semantics_verified=True, capacity_unit="m3/s",
        )
        event = HydrologicEvent("hat-yai-compound", EventState.RECESSION, 0, 1, False, True, ["wave-a", "wave-b"])
        self.assertIsNone(capacity.value)
        self.assertEqual(capacity.uncertainty, "HIGH")
        self.assertFalse(event.can_end())


if __name__ == "__main__":
    unittest.main()
