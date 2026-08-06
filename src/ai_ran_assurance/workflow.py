import logging
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from ai_ran_assurance.config import ProjectConfig, load_config
from ai_ran_assurance.detection import IsolationForestDetector, RuleDetector
from ai_ran_assurance.diagnosis import RootCauseEngine
from ai_ran_assurance.domain.enums import AnomalyType
from ai_ran_assurance.domain.models import (
    Anomaly,
    CorrectiveAction,
    FaultScenario,
    KPISample,
    NetworkTopology,
    RootCauseDiagnosis,
    ShadowDecision,
)
from ai_ran_assurance.simulation import KPIGenerator, build_network
from ai_ran_assurance.twin import (
    ActionRecommender,
    GuardrailValidator,
    NetworkTwin,
    TwinSimulator,
    shadow_decision,
)

LOGGER = logging.getLogger(__name__)


class ScenarioRun(BaseModel):
    scenario: FaultScenario
    topology: NetworkTopology
    telemetry: list[KPISample]
    anomalies: list[Anomaly]
    diagnoses: list[RootCauseDiagnosis]
    recommendations: list[CorrectiveAction]
    decisions: list[ShadowDecision]
    evaluation_mode: Literal["synthetic_replay"] = "synthetic_replay"
    training_seed: int
    evaluation_seed: int
    generated_at: datetime


class ClosedLoopEngine:
    """Synthetic telemetry-to-shadow-decision workflow."""

    def __init__(
        self, config: ProjectConfig | None = None, *, training_seed: int | None = None
    ) -> None:
        self.config = config or load_config()
        self.training_seed = self.config.network.seed if training_seed is None else training_seed
        self.topology = build_network(self.config.network)
        self.generator = KPIGenerator(self.topology, self.config.network)
        self.rules = RuleDetector(self.config.thresholds)
        baseline = self.generator.generate(
            self.config.network.baseline_steps,
            seed=self.training_seed,
        )
        self.ml = IsolationForestDetector(seed=self.training_seed).fit(baseline)
        self.rca = RootCauseEngine(self.config.thresholds)
        self.recommender = ActionRecommender()
        self.twin_simulator = TwinSimulator()
        self.guardrails = GuardrailValidator(self.config.thresholds)

    def run(
        self,
        scenario_name: str,
        *,
        steps: int | None = None,
        seed: int | None = None,
    ) -> ScenarioRun:
        return self.run_scenario(self.config.scenario(scenario_name), steps=steps, seed=seed)

    def run_scenario(
        self,
        scenario: FaultScenario,
        *,
        steps: int | None = None,
        seed: int | None = None,
    ) -> ScenarioRun:
        # Training needs a full daily baseline; evaluation only needs a short post-fault
        # window so a replay does not turn every finding into stale historical evidence.
        run_steps = steps or scenario.start_step + scenario.duration + 2
        if run_steps <= scenario.start_step:
            raise ValueError("steps must extend beyond the scenario start")
        evaluation_seed = self.config.network.seed + 1 if seed is None else seed
        telemetry = self.generator.generate(run_steps, scenario, seed=evaluation_seed)
        rule_anomalies = self.rules.detect(telemetry)
        ml_anomalies = self.ml.detect(telemetry)
        ml_keys = {(item.cell_id, item.timestamp) for item in ml_anomalies}
        # Hard safety thresholds stand alone; lower-specificity rolling anomalies require
        # independent Isolation Forest agreement. This keeps the fusion explainable.
        fused = [
            item
            for item in rule_anomalies
            if item.anomaly_type is AnomalyType.THRESHOLD
            or (item.cell_id, item.timestamp) in ml_keys
        ]
        anomaly_map = {(item.cell_id, item.timestamp): item for item in fused}
        anomalies = sorted(anomaly_map.values(), key=lambda item: (item.timestamp, item.cell_id))
        sample_map = {(item.cell_id, item.timestamp): item for item in telemetry}
        replay_time = max(item.timestamp for item in telemetry)
        latest_by_cell: dict[str, Anomaly] = {}
        for anomaly in anomalies:
            latest_by_cell[anomaly.cell_id] = anomaly
        diagnoses: list[RootCauseDiagnosis] = []
        recommendations: list[CorrectiveAction] = []
        decisions: list[ShadowDecision] = []
        for anomaly in latest_by_cell.values():
            sample = sample_map[(anomaly.cell_id, anomaly.timestamp)]
            diagnosis = self.rca.diagnose(anomaly, sample)
            action = self.recommender.recommend(diagnosis, proposed_at=sample.timestamp)
            timestamp_samples = [item for item in telemetry if item.timestamp == sample.timestamp]
            prediction = self.twin_simulator.simulate(
                NetworkTwin(self.topology, timestamp_samples), action
            )
            guardrail = self.guardrails.validate(
                action,
                prediction,
                telemetry_timestamp=sample.timestamp,
                evaluated_at=replay_time,
            )
            diagnoses.append(diagnosis)
            recommendations.append(action)
            decisions.append(shadow_decision(action, prediction, guardrail))
        LOGGER.info(
            "closed_loop_completed scenario=%s training_seed=%d evaluation_seed=%d "
            "telemetry=%d anomalies=%d decisions=%d",
            scenario.name,
            self.training_seed,
            evaluation_seed,
            len(telemetry),
            len(anomalies),
            len(decisions),
        )
        return ScenarioRun(
            scenario=scenario,
            topology=self.topology,
            telemetry=telemetry,
            anomalies=anomalies,
            diagnoses=diagnoses,
            recommendations=recommendations,
            decisions=decisions,
            training_seed=self.training_seed,
            evaluation_seed=evaluation_seed,
            generated_at=datetime.now(UTC),
        )
