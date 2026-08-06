from copy import deepcopy

from ai_ran_assurance.domain.models import KPISample, NetworkTopology


class NetworkTwin:
    """Copyable topology, configuration, traffic, and latest-KPI representation."""

    def __init__(self, topology: NetworkTopology, telemetry: list[KPISample]) -> None:
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

    def restore_neighbor(self, cell_id: str) -> str | None:
        for relation in self.topology.neighbor_relations:
            if relation.source_cell == cell_id and not relation.enabled:
                relation.enabled = True
                return relation.target_cell
        candidates = [
            cell.cell_id
            for cell in self.topology.cells
            if cell.cell_id != cell_id and cell.cell_id not in self.neighbors(cell_id)
        ]
        if candidates:
            from ai_ran_assurance.domain.models import NeighborRelation

            self.topology.neighbor_relations.append(
                NeighborRelation(source_cell=cell_id, target_cell=candidates[0])
            )
            return candidates[0]
        return None
