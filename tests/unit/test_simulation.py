from datetime import UTC, datetime

import pytest

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.domain.enums import RootCauseCategory
from ai_ran_assurance.simulation import KPIGenerator, build_network
from ai_ran_assurance.simulation.network import topology_graph


def test_network_has_deterministic_connected_topology(project_config: ProjectConfig) -> None:
    first = build_network(project_config.network)
    second = build_network(project_config.network)
    assert first == second
    assert len(first.cells) == 20
    assert len(first.neighbor_relations) == 80
    assert all(topology_graph(first).out_degree(cell.cell_id) == 4 for cell in first.cells)


def test_generation_is_reproducible_and_correlated(project_config: ProjectConfig) -> None:
    generator = KPIGenerator(build_network(project_config.network), project_config.network)
    first = generator.generate(8, seed=123)
    second = generator.generate(8, seed=123)
    different = generator.generate(8, seed=124)
    assert first == second
    assert first != different
    assert len(first) == 160
    low_load = min(first, key=lambda item: item.prb_utilization_pct)
    high_load = max(first, key=lambda item: item.prb_utilization_pct)
    assert high_load.latency_ms > low_load.latency_ms
    with pytest.raises(ValueError, match="positive"):
        generator.generate(0)


@pytest.mark.parametrize(
    ("scenario_name", "field"),
    [
        ("congestion", "prb_utilization_pct"),
        ("interference", "bler_pct"),
        ("missing_neighbor", "call_drop_pct"),
        ("outage", "availability_pct"),
        ("transport_latency", "latency_ms"),
        ("coverage", "rsrp_dbm"),
        ("bler", "bler_pct"),
        ("mobility", "handover_success_pct"),
    ],
)
def test_all_faults_change_correlated_kpis(
    project_config: ProjectConfig, scenario_name: str, field: str
) -> None:
    generator = KPIGenerator(build_network(project_config.network), project_config.network)
    scenario = project_config.scenario(scenario_name)
    start = datetime(2026, 2, 1, tzinfo=UTC)
    normal = generator.generate(60, start=start, seed=99)
    faulty = generator.generate(60, scenario, start=start, seed=99)
    target = scenario.target_cells[0]
    step = scenario.start_step + 1
    normal_sample = next(item for item in normal if item.cell_id == target and item.step == step)
    faulty_sample = next(item for item in faulty if item.cell_id == target and item.step == step)
    assert getattr(normal_sample, field) != getattr(faulty_sample, field)
    assert faulty_sample.ground_truth is scenario.ground_truth
    unaffected = next(item for item in faulty if item.cell_id != target and item.step == step)
    assert unaffected.ground_truth is RootCauseCategory.NORMAL
