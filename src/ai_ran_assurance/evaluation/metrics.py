from dataclasses import dataclass


@dataclass(frozen=True)
class BinaryMetrics:
    precision: float
    recall: float
    f1_score: float
    false_alarm_rate: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "false_alarm_rate": self.false_alarm_rate,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
        }


def binary_metrics(truth: list[bool], predicted: list[bool]) -> BinaryMetrics:
    if len(truth) != len(predicted) or not truth:
        raise ValueError("truth and predicted must be non-empty and have equal length")
    true_positives = sum(
        expected and actual for expected, actual in zip(truth, predicted, strict=True)
    )
    false_positives = sum(
        not expected and actual for expected, actual in zip(truth, predicted, strict=True)
    )
    true_negatives = sum(
        not expected and not actual for expected, actual in zip(truth, predicted, strict=True)
    )
    false_negatives = sum(
        expected and not actual for expected, actual in zip(truth, predicted, strict=True)
    )
    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )
    f1_score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    false_alarm_rate = (
        false_positives / (false_positives + true_negatives)
        if false_positives + true_negatives
        else 0.0
    )
    return BinaryMetrics(
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1_score=round(f1_score, 6),
        false_alarm_rate=round(false_alarm_rate, 6),
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
    )
