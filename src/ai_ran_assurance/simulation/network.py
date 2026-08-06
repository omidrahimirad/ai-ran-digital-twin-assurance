from __future__ import annotations

import networkx as nx

from ai_ran_assurance.config import NetworkSettings
from ai_ran_assurance.domain.models import (
    Cell,
    CellConfiguration,
    NeighborRelation,
    NetworkTopology,
)


def build_network(settings: NetworkSettings) -> NetworkTopology:
    """Build a deterministic ring-plus-chords topology with at least 20 cells."""
    graph = nx.watts_strogatz_graph(settings.cell_count, 4, 0, seed=settings.seed)
    cells = [
        Cell(
            cell_id=f"CELL-{index + 1:03d}",
            capacity_mbps=settings.capacity_mbps * (0.9 + 0.02 * (index % 6)),
            transmit_power_dbm=settings.transmit_power_dbm - 0.5 * (index % 3),
            traffic_profile=settings.traffic_profile,
            configuration=CellConfiguration(
                transmit_power_dbm=settings.transmit_power_dbm - 0.5 * (index % 3),
                capacity_mbps=settings.capacity_mbps * (0.9 + 0.02 * (index % 6)),
            ),
        )
        for index in range(settings.cell_count)
    ]
    relations: list[NeighborRelation] = []
    for source, target in sorted(graph.edges()):
        first = f"CELL-{source + 1:03d}"
        second = f"CELL-{target + 1:03d}"
        relations.extend(
            [
                NeighborRelation(source_cell=first, target_cell=second),
                NeighborRelation(source_cell=second, target_cell=first),
            ]
        )
    return NetworkTopology(cells=cells, neighbor_relations=relations)


def topology_graph(topology: NetworkTopology) -> nx.DiGraph[str]:
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(cell.cell_id for cell in topology.cells)
    graph.add_edges_from(
        (relation.source_cell, relation.target_cell)
        for relation in topology.neighbor_relations
        if relation.enabled
    )
    return graph
