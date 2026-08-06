import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from ai_ran_assurance.domain.enums import AnomalyType, RootCauseCategory
from ai_ran_assurance.domain.models import Anomaly, KPISample
from ai_ran_assurance.simulation.kpi_generator import KPI_NAMES


def _matrix(samples: list[KPISample]) -> np.ndarray:
    return np.asarray(
        [[float(getattr(sample, name)) for name in KPI_NAMES] for sample in samples],
        dtype=np.float64,
    )


class IsolationForestDetector:
    """Reproducible unsupervised detector fitted exclusively to normal samples."""

    name = "isolation_forest"

    def __init__(self, seed: int = 42, contamination: float = 0.02) -> None:
        if not 0 < contamination <= 0.5:
            raise ValueError("contamination must be in (0, 0.5]")
        self.scaler = StandardScaler()
        self.model = IsolationForest(
            n_estimators=150,
            contamination=contamination,
            random_state=seed,
            n_jobs=1,
        )
        self.fitted = False

    def fit(self, samples: list[KPISample]) -> "IsolationForestDetector":
        if any(sample.ground_truth is not RootCauseCategory.NORMAL for sample in samples):
            raise ValueError("training data must be a prequalified all-normal baseline")
        if len(samples) < 20:
            raise ValueError("at least 20 normal baseline samples are required")
        self.model.fit(self.scaler.fit_transform(_matrix(samples)))
        self.fitted = True
        return self

    def detect(self, samples: list[KPISample]) -> list[Anomaly]:
        if not self.fitted:
            raise RuntimeError("detector must be fitted on normal baseline samples")
        if not samples:
            return []
        matrix = self.scaler.transform(_matrix(samples))
        scores = self.model.decision_function(matrix)
        labels = self.model.predict(matrix)
        return [
            Anomaly(
                cell_id=sample.cell_id,
                timestamp=sample.timestamp,
                anomaly_type=AnomalyType.ML,
                score=round(float(max(0.0, -score)), 4),
                evidence={name: float(getattr(sample, name)) for name in KPI_NAMES},
                detector=self.name,
            )
            for sample, label, score in zip(samples, labels, scores, strict=True)
            if label == -1
        ]
