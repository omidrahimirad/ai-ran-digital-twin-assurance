from datetime import UTC, datetime
from statistics import correlation, mean

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
    assert (
        correlation(
            [item.prb_utilization_pct for item in first], [item.latency_ms for item in first]
        )
        > 0.95
    )
    assert correlation([item.sinr_db for item in first], [item.bler_pct for item in first]) < -0.9
    capacities = {cell.cell_id: cell.capacity_mbps for cell in generator.topology.cells}
    assert all(item.throughput_mbps <= capacities[item.cell_id] for item in first)
    with pytest.raises(ValueError, match="positive"):
        generator.generate(0)
    with pytest.raises(ValueError, match="timezone-aware"):
        generator.generate(1, start=datetime(2026, 1, 1))


def test_daily_profile_and_temporal_state_are_real_and_reproducible(
    project_config: ProjectConfig,
) -> None:
    generator = KPIGenerator(build_network(project_config.network), project_config.network)
    samples = generator.generate(288, seed=123)
    target = [item for item in samples if item.cell_id == "CELL-001"]
    overnight = [item.prb_utilization_pct for item in target if 0 <= item.step < 48]
    evening = [item.prb_utilization_pct for item in target if 204 <= item.step < 228]
    assert mean(evening) > mean(overnight) + 20
    assert (
        correlation(
            [item.prb_utilization_pct for item in target[:-1]],
            [item.prb_utilization_pct for item in target[1:]],
        )
        > 0.8
    )
    midnight = generator.generate(1, start=datetime(2026, 1, 1, tzinfo=UTC), seed=123)
    evening_start = generator.generate(1, start=datetime(2026, 1, 1, 18, tzinfo=UTC), seed=123)
    assert (
        mean(item.prb_utilization_pct for item in evening_start)
        > mean(item.prb_utilization_pct for item in midnight) + 20
    )


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
    steps = scenario.start_step + 2
    normal = generator.generate(steps, start=start, seed=99)
    faulty = generator.generate(steps, scenario, start=start, seed=99)
    target = scenario.target_cells[0]
    step = scenario.start_step + 1
    normal_sample = next(item for item in normal if item.cell_id == target and item.step == step)
    faulty_sample = next(item for item in faulty if item.cell_id == target and item.step == step)
    assert getattr(normal_sample, field) != getattr(faulty_sample, field)
    assert faulty_sample.ground_truth is scenario.ground_truth
    unaffected = next(item for item in faulty if item.cell_id != target and item.step == step)
    assert unaffected.ground_truth is RootCauseCategory.NORMAL
