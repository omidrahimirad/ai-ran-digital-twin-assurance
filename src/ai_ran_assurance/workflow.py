import logging
from datetime import UTC, datetime

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
    generated_at: datetime


class ClosedLoopEngine:
    """Synthetic telemetry-to-shadow-decision workflow."""

    def __init__(self, config: ProjectConfig | None = None) -> None:
        self.config = config or load_config()
        self.topology = build_network(self.config.network)
        self.generator = KPIGenerator(self.topology, self.config.network)
        self.rules = RuleDetector(self.config.thresholds)
        baseline = self.generator.generate(
            self.config.network.baseline_steps,
            seed=self.config.network.seed,
        )
        self.ml = IsolationForestDetector(seed=self.config.network.seed).fit(baseline)
        self.rca = RootCauseEngine()
        self.recommender = ActionRecommender()
        self.twin_simulator = TwinSimulator()
        self.guardrails = GuardrailValidator(self.config.thresholds)

    def run(self, scenario_name: str, *, steps: int | None = None) -> ScenarioRun:
        scenario = self.config.scenario(scenario_name)
        run_steps = steps or max(
            self.config.network.baseline_steps, scenario.start_step + scenario.duration + 6
        )
        if run_steps <= scenario.start_step:
            raise ValueError("steps must extend beyond the scenario start")
        telemetry = self.generator.generate(
            run_steps,
            scenario,
            seed=self.config.network.seed + 1,
        )
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
        selected = [
            anomaly
            for anomaly in anomalies
            if anomaly.cell_id in scenario.target_cells
            and scenario.start_step
            <= sample_map[(anomaly.cell_id, anomaly.timestamp)].step
            < scenario.start_step + scenario.duration
        ]
        latest_by_cell: dict[str, Anomaly] = {}
        for anomaly in selected:
            latest_by_cell[anomaly.cell_id] = anomaly
        diagnoses: list[RootCauseDiagnosis] = []
        recommendations: list[CorrectiveAction] = []
        decisions: list[ShadowDecision] = []
        for anomaly in latest_by_cell.values():
            sample = sample_map[(anomaly.cell_id, anomaly.timestamp)]
            diagnosis = self.rca.diagnose(anomaly, sample)
            action = self.recommender.recommend(diagnosis, proposed_at=sample.timestamp)
            prediction = self.twin_simulator.simulate(NetworkTwin(self.topology, [sample]), action)
            guardrail = self.guardrails.validate(
                action,
                prediction,
                telemetry_timestamp=sample.timestamp,
                evaluated_at=sample.timestamp,
            )
            diagnoses.append(diagnosis)
            recommendations.append(action)
            decisions.append(shadow_decision(action, prediction, guardrail))
        if not decisions:
            raise RuntimeError(f"scenario {scenario_name!r} produced no actionable anomaly")
        LOGGER.info(
            "closed_loop_completed scenario=%s telemetry=%d anomalies=%d decisions=%d",
            scenario_name,
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
            generated_at=datetime.now(UTC),
        )
