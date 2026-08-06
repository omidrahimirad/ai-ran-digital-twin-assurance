from datetime import UTC, datetime

import pytest

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.detection import IsolationForestDetector, RuleDetector
from ai_ran_assurance.diagnosis import RootCauseEngine
from ai_ran_assurance.domain.enums import AnomalyType, RootCauseCategory
from ai_ran_assurance.domain.models import Anomaly
from ai_ran_assurance.simulation import KPIGenerator, build_network


def test_isolation_forest_lifecycle(project_config: ProjectConfig) -> None:
    generator = KPIGenerator(build_network(project_config.network), project_config.network)
    baseline = generator.generate(project_config.network.baseline_steps, seed=10)
    detector = IsolationForestDetector(seed=10)
    with pytest.raises(RuntimeError, match="fitted"):
        detector.detect(baseline[:1])
    with pytest.raises(ValueError, match="20 normal"):
        detector.fit(baseline[:10])
    contaminated = baseline.copy()
    contaminated[0] = contaminated[0].model_copy(
        update={"ground_truth": RootCauseCategory.CELL_OUTAGE}
    )
    with pytest.raises(ValueError, match="all-normal"):
        detector.fit(contaminated)
    detector.fit(baseline)
    assert detector.detect([]) == []
    scenario = project_config.scenario("outage")
    outage = generator.generate(scenario.start_step + scenario.duration, scenario, seed=11)
    severe = [item for item in outage if item.ground_truth is RootCauseCategory.CELL_OUTAGE]
    assert detector.detect(severe)


def test_rules_and_rca_identify_every_configured_scenario(project_config: ProjectConfig) -> None:
    generator = KPIGenerator(build_network(project_config.network), project_config.network)
    detector = RuleDetector(project_config.thresholds)
    engine = RootCauseEngine(project_config.thresholds)
    for scenario in project_config.scenarios:
        samples = generator.generate(scenario.start_step + scenario.duration, scenario, seed=43)
        anomalies = detector.detect(samples)
        sample_map = {(item.cell_id, item.timestamp): item for item in samples}
        anomaly = next(
            item
            for item in anomalies
            if sample_map[(item.cell_id, item.timestamp)].ground_truth
            is not RootCauseCategory.NORMAL
        )
        sample = sample_map[(anomaly.cell_id, anomaly.timestamp)]
        diagnosis = engine.diagnose(anomaly, sample)
        expected = (
            RootCauseCategory.UNKNOWN
            if scenario.name in {"missing_neighbor", "mobility"}
            else scenario.ground_truth
        )
        assert diagnosis.probable_root_cause is expected
        assert diagnosis.explanation
        assert diagnosis.next_diagnostic_check


def test_mobility_signature_is_not_forced_to_a_specific_configuration_cause(
    project_config: ProjectConfig,
) -> None:
    generator = KPIGenerator(build_network(project_config.network), project_config.network)
    scenario = project_config.scenario("missing_neighbor")
    samples = generator.generate(scenario.start_step + scenario.duration, scenario, seed=43)
    sample = next(
        item
        for item in samples
        if item.ground_truth is RootCauseCategory.NEIGHBOR_RELATION
        and item.handover_success_pct < 94
        and item.call_drop_pct > 2
    )
    anomaly = Anomaly(
        cell_id=sample.cell_id,
        timestamp=sample.timestamp,
        anomaly_type=AnomalyType.THRESHOLD,
        score=1,
        evidence={
            "handover_success_pct": sample.handover_success_pct,
            "call_drop_pct": sample.call_drop_pct,
        },
        detector="test",
    )
    diagnosis = RootCauseEngine(project_config.thresholds).diagnose(anomaly, sample)
    assert diagnosis.probable_root_cause is RootCauseCategory.UNKNOWN
    assert "cannot distinguish" in diagnosis.explanation
    assert "neighbor state" in diagnosis.next_diagnostic_check


def test_rca_rejects_mismatched_evidence_and_has_unknown_fallback(
    project_config: ProjectConfig,
) -> None:
    sample = KPIGenerator(build_network(project_config.network), project_config.network).generate(
        1
    )[0]
    anomaly = Anomaly(
        cell_id=sample.cell_id,
        timestamp=sample.timestamp,
        anomaly_type=AnomalyType.STATISTICAL,
        score=1,
        evidence={"sinr_db": sample.sinr_db},
        detector="test",
    )
    engine = RootCauseEngine(project_config.thresholds)
    diagnosis = engine.diagnose(anomaly, sample)
    assert diagnosis.probable_root_cause is RootCauseCategory.UNKNOWN
    wrong = anomaly.model_copy(update={"timestamp": datetime(2020, 1, 1, tzinfo=UTC)})
    with pytest.raises(ValueError, match="same cell and timestamp"):
        engine.diagnose(wrong, sample)
