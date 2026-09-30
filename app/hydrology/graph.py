"""Typed dynamic water graph with conservative flow-direction resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NodeType(StrEnum):
    SOURCE = "SOURCE"
    CATCHMENT = "CATCHMENT"
    SUBCATCHMENT = "SUBCATCHMENT"
    HEADWATER = "HEADWATER"
    GAUGE = "GAUGE"
    JUNCTION = "JUNCTION"
    CONFLUENCE = "CONFLUENCE"
    RESERVOIR = "RESERVOIR"
    DIVERSION = "DIVERSION"
    GATE = "GATE"
    PUMP = "PUMP"
    CANAL_CONNECTION = "CANAL_CONNECTION"
    TIDE_BOUNDARY = "TIDE_BOUNDARY"
    OUTLET = "OUTLET"
    FLOODPLAIN_STORAGE = "FLOODPLAIN_STORAGE"


class EdgeType(StrEnum):
    RIVER_REACH = "RIVER_REACH"
    CREEK = "CREEK"
    CANAL = "CANAL"
    CONTROLLED_CANAL = "CONTROLLED_CANAL"
    DIVERSION = "DIVERSION"
    GATE_PATH = "GATE_PATH"
    PUMP_PATH = "PUMP_PATH"
    FLOODPLAIN_CONNECTION = "FLOODPLAIN_CONNECTION"
    ESTUARY = "ESTUARY"


class EdgeDirection(StrEnum):
    FORWARD = "FORWARD"
    REVERSE = "REVERSE"
    BIDIRECTIONAL = "BIDIRECTIONAL"
    CONTROLLED = "CONTROLLED"
    DYNAMIC = "DYNAMIC"


class EffectiveDirection(StrEnum):
    FORWARD = "FORWARD"
    REVERSE = "REVERSE"
    BIDIRECTIONAL = "BIDIRECTIONAL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: NodeType


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    from_node_id: str
    to_node_id: str
    edge_type: EdgeType
    direction: EdgeDirection


@dataclass(frozen=True)
class FlowEvidence:
    upstream_stage: float | None = None
    downstream_stage: float | None = None
    stages_share_datum: bool = False
    stages_fresh: bool = False
    semantics_verified: bool = False
    gate_state: str = "UNKNOWN"
    pump_state: str = "UNKNOWN"
    pump_direction: str | None = None


def effective_direction(edge: GraphEdge, evidence: FlowEvidence | None = None) -> EffectiveDirection:
    """Resolve controlled/dynamic direction only from fresh, comparable evidence."""
    if edge.direction == EdgeDirection.FORWARD:
        return EffectiveDirection.FORWARD
    if edge.direction == EdgeDirection.REVERSE:
        return EffectiveDirection.REVERSE
    if edge.direction == EdgeDirection.BIDIRECTIONAL:
        return EffectiveDirection.BIDIRECTIONAL
    if evidence is None or not evidence.semantics_verified:
        return EffectiveDirection.UNKNOWN

    if edge.edge_type in {EdgeType.GATE_PATH, EdgeType.CONTROLLED_CANAL}:
        if evidence.gate_state == "CLOSED":
            return EffectiveDirection.BLOCKED
        if evidence.gate_state != "OPEN":
            return EffectiveDirection.UNKNOWN

    if edge.edge_type == EdgeType.PUMP_PATH:
        if evidence.pump_state == "OFF":
            return EffectiveDirection.BLOCKED
        if evidence.pump_state != "ON":
            return EffectiveDirection.UNKNOWN
        if evidence.pump_direction == "FORWARD":
            return EffectiveDirection.FORWARD
        if evidence.pump_direction == "REVERSE":
            return EffectiveDirection.REVERSE
        return EffectiveDirection.UNKNOWN

    if not evidence.stages_fresh or not evidence.stages_share_datum:
        return EffectiveDirection.UNKNOWN
    if evidence.upstream_stage is None or evidence.downstream_stage is None:
        return EffectiveDirection.UNKNOWN
    if evidence.upstream_stage > evidence.downstream_stage:
        return EffectiveDirection.FORWARD
    if evidence.upstream_stage < evidence.downstream_stage:
        return EffectiveDirection.REVERSE
    return EffectiveDirection.UNKNOWN
