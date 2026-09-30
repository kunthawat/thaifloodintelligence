"""Event and wave state transitions without premature event termination."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EventState(StrEnum):
    GENERATING = "GENERATING"
    HEADWATER_ROUTING = "HEADWATER_ROUTING"
    TRIBUTARY_ROUTING = "TRIBUTARY_ROUTING"
    MAIN_RIVER_ROUTING = "MAIN_RIVER_ROUTING"
    FLOODPLAIN_FILLING = "FLOODPLAIN_FILLING"
    RECESSION = "RECESSION"
    ENDED = "ENDED"


@dataclass
class HydrologicEvent:
    event_id: str
    state: EventState
    material_runoff_pulses_remaining: int
    material_upstream_waves_remaining: int
    linked_forecast_rainfall: bool
    recession_established: bool
    waves: list[str] = field(default_factory=list)

    def can_end(self) -> bool:
        """A falling local level alone is never enough to end an event."""
        return (
            self.material_runoff_pulses_remaining == 0
            and self.material_upstream_waves_remaining == 0
            and not self.linked_forecast_rainfall
            and self.recession_established
        )

    def refresh_terminal_state(self) -> EventState:
        if self.can_end():
            self.state = EventState.ENDED
        elif self.state == EventState.ENDED:
            self.state = EventState.RECESSION
        return self.state
