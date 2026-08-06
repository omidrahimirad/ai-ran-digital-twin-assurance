from copy import deepcopy

from ai_ran_assurance.domain.models import CellConfiguration, KPISample, NetworkTopology


class NetworkTwin:
    """Copyable topology, configuration, traffic, and latest-KPI representation."""

    def __init__(self, topology: NetworkTopology, telemetry: list[KPISample]) -> None:
        if not telemetry:
            raise ValueError("twin telemetry cannot be empty")
        if len({sample.cell_id for sample in telemetry}) != len(telemetry):
            raise ValueError("twin telemetry must contain one sample per cell")
        if len({sample.timestamp for sample in telemetry}) != 1:
            raise ValueError("twin telemetry must represent one timestamp")
        known_cells = {cell.cell_id for cell in topology.cells}
        unknown = {sample.cell_id for sample in telemetry} - known_cells
        if unknown:
            raise ValueError(f"twin telemetry contains unknown cells: {sorted(unknown)}")
        self.topology = topology.model_copy(deep=True)
        self.current_kpis = {sample.cell_id: sample.model_copy(deep=True) for sample in telemetry}
        self.current_traffic = {sample.cell_id: sample.prb_utilization_pct for sample in telemetry}

    def copy(self) -> "NetworkTwin":
        return deepcopy(self)

    def sample(self, cell_id: str) -> KPISample:
        try:
            return self.current_kpis[cell_id]
        except KeyError as exc:
            raise ValueError(f"unknown cell {cell_id!r} in twin state") from exc

    def neighbors(self, cell_id: str) -> list[str]:
        return [
            relation.target_cell
            for relation in self.topology.neighbor_relations
            if relation.source_cell == cell_id and relation.enabled
        ]

    def restore_neighbor(self, cell_id: str, target_cell: str) -> None:
        for relation in self.topology.neighbor_relations:
            if relation.source_cell == cell_id and relation.target_cell == target_cell:
                if relation.enabled:
                    raise ValueError("requested neighbor relation is already enabled")
                relation.enabled = True
                return
        raise ValueError("requested disabled neighbor relation does not exist")

    def cell_configuration(self, cell_id: str) -> CellConfiguration:
        try:
            return next(
                cell.configuration for cell in self.topology.cells if cell.cell_id == cell_id
            )
        except StopIteration as exc:
            raise ValueError(f"unknown cell {cell_id!r} in twin topology") from exc
