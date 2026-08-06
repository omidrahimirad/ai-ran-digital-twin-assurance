import pytest

from ai_ran_assurance.evaluation.metrics import binary_metrics


def test_binary_metrics_exact_values() -> None:
    result = binary_metrics([True, True, False, False], [True, False, True, False])
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1_score == 0.5
    assert result.false_alarm_rate == 0.5
    assert result.as_dict()["true_negatives"] == 1


@pytest.mark.parametrize(("truth", "predicted"), [([], []), ([True], []), ([], [False])])
def test_binary_metrics_reject_invalid_inputs(truth: list[bool], predicted: list[bool]) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        binary_metrics(truth, predicted)
