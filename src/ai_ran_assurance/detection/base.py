from typing import Protocol

from ai_ran_assurance.domain.models import Anomaly, KPISample


class Detector(Protocol):
    name: str

    def detect(self, samples: list[KPISample]) -> list[Anomaly]: ...
