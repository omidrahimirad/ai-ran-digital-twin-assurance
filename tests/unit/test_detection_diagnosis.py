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
    detector.fit(baseline)
    assert detector.detect([]) == []
    outage = generator.generate(48, project_config.scenario("outage"), seed=11)
    severe = [item for item in outage if item.ground_truth is RootCauseCategory.CELL_OUTAGE]
    assert detector.detect(severe)


def test_rules_and_rca_identify_every_configured_scenario(project_config: ProjectConfig) -> None:
    generator = KPIGenerator(build_network(project_config.network), project_config.network)
    detector = RuleDetector(project_config.thresholds)
    engine = RootCauseEngine()
    for scenario in project_config.scenarios:
        samples = generator.generate(60, scenario, seed=43)
        anomalies = detector.detect(samples)
        sample = [item for item in samples if item.ground_truth is not RootCauseCategory.NORMAL][-1]
        anomaly = next(
            item
            for item in reversed(anomalies)
            if item.cell_id == sample.cell_id and item.timestamp == sample.timestamp
        )
        diagnosis = engine.diagnose(anomaly, sample)
        assert diagnosis.probable_root_cause is scenario.ground_truth
        assert diagnosis.explanation
        assert diagnosis.next_diagnostic_check


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
    diagnosis = RootCauseEngine().diagnose(anomaly, sample)
    assert diagnosis.probable_root_cause is RootCauseCategory.UNKNOWN
    wrong = anomaly.model_copy(update={"timestamp": datetime(2020, 1, 1, tzinfo=UTC)})
    with pytest.raises(ValueError, match="same cell and timestamp"):
        RootCauseEngine().diagnose(wrong, sample)
