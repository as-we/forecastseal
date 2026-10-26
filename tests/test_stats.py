import math
import pytest
from forecastseal import stats


def test_losses_have_known_values():
    assert stats.log_loss({"y": 0.8, "n": 0.2}, "y") == pytest.approx(-math.log(0.8))
    assert stats.brier({"y": 0.8, "n": 0.2}, "y") == pytest.approx(0.04 + 0.04)
    assert stats.log_loss({"y": 0.0, "n": 1.0}, "y") < 40            # clipped, not infinite


def test_perfect_calibration_has_low_ece():
    rows = [{"forecaster": "f", "event": str(i), "probs": {"y": 0.7, "n": 0.3}, "outcome": "y" if i % 10 < 7 else "n"} for i in range(1000)]
    assert stats.calibration(rows)["ece"] < 0.01


def test_overconfidence_shows_up_in_ece():
    rows = [{"forecaster": "f", "event": str(i), "probs": {"y": 0.95, "n": 0.05}, "outcome": "y" if i % 2 else "n"} for i in range(1000)]
    assert stats.calibration(rows)["ece"] > 0.4


def test_required_n_matches_textbook():
    # two-sided alpha .05, power .8, effect = 1 sd -> (1.96 + 0.8416)^2 = 7.85 -> 8
    assert stats.required_n(delta=1.0, sd=1.0, alpha=0.05) == 8
    assert stats.power(8, 1.0, 1.0, 0.05) == pytest.approx(0.80, abs=0.03)


def test_power_grows_with_n_and_effect():
    assert stats.power(400, 0.004, 0.085, 0.05) > stats.power(100, 0.004, 0.085, 0.05)
    assert stats.power(200, 0.008, 0.085, 0.05) > stats.power(200, 0.004, 0.085, 0.05)
    assert stats.power(200, 0.0, 0.085, 0.05) == pytest.approx(0.05, abs=0.001)   # no effect: false-positive rate


def test_min_detectable_and_required_n_are_consistent():
    n = stats.required_n(0.004, 0.085, 0.05)
    assert stats.min_detectable(n, 0.085, 0.05) <= 0.004 + 1e-9


def test_bootstrap_is_reproducible_and_covers_the_mean():
    v = [0.01 * ((i % 7) - 3) + 0.02 for i in range(200)]
    a = stats.bootstrap_ci(v, 0.95, seed=1)
    assert a == stats.bootstrap_ci(v, 0.95, seed=1)
    assert a[0] < sum(v) / len(v) < a[1]


def test_compare_detects_a_real_difference_and_not_a_null_one():
    import random
    rng = random.Random(3)
    rows = []
    for i in range(300):
        base = rng.random() * 0.6 + 0.2
        out = "y" if rng.random() < base else "n"
        rows.append({"forecaster": "good", "event": str(i), "probs": {"y": base, "n": 1 - base}, "outcome": out})
        rows.append({"forecaster": "flat", "event": str(i), "probs": {"y": 0.5, "n": 0.5}, "outcome": out})
        rows.append({"forecaster": "twin", "event": str(i), "probs": {"y": base, "n": 1 - base}, "outcome": out})
    assert stats.compare(rows, "log_loss", "good", "flat", 0.05)["excludes_zero"]
    assert not stats.compare(rows, "log_loss", "good", "twin", 0.05)["excludes_zero"]


def test_multiplicity_widens_the_interval():
    import random
    rng = random.Random(5)
    d = [rng.gauss(0.01, 0.1) for _ in range(150)]
    rows = []
    for i, x in enumerate(d):
        rows.append({"forecaster": "a", "event": str(i), "probs": {"y": 0.5, "n": 0.5}, "outcome": "y"})
    lo1, hi1 = stats.bootstrap_ci(d, 0.95)
    lo2, hi2 = stats.bootstrap_ci(d, 1 - 0.05 / 10)
    assert (hi2 - lo2) > (hi1 - lo1)


def test_two_predictions_by_one_forecaster_for_one_event_is_an_error():
    rows = [{"forecaster": "f", "event": "e", "probs": {"y": 0.5, "n": 0.5}, "outcome": "y"}] * 2
    with pytest.raises(ValueError):
        stats.score(rows, "log_loss")
