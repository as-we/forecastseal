import pytest
from forecastseal import stats
from forecastseal.cli import main


def test_required_n_rates_matches_textbook():
    # 0.5 vs 0.6, alpha 0.05, power 0.8: about 388 per group (standard two-proportion formula)
    assert abs(stats.required_n_rates(0.5, 0.6, 0.05) - 388) <= 2
    assert stats.required_n_rates(0.7, 0.75, 0.05) > stats.required_n_rates(0.7, 0.8, 0.05)


def test_power_rates_is_consistent_with_required_n():
    n = stats.required_n_rates(0.6, 0.7, 0.05)
    assert 0.79 <= stats.power_rates(n, 0.6, 0.7, 0.05) <= 0.85
    assert stats.power_rates(20, 0.6, 0.7, 0.05) < 0.2


def test_rates_reject_bad_input():
    for bad in ((0.5, 0.5), (0.0, 0.5), (0.5, 1.0)):
        with pytest.raises(ValueError):
            stats.required_n_rates(*bad, 0.05)


def test_plan_split_arithmetic():
    r = stats.plan_split(300, (50, 20, 30), needed=1100, power_at=lambda n: 0.3)
    assert r["stages"] == {"explore": 150, "validate": 60, "confirm": 90}
    assert r["sufficiency"] == pytest.approx(90 / 1100) and r["if_all_data_confirm"] == pytest.approx(300 / 1100)
    r2 = stats.plan_split(1001, (50, 20, 30), needed=100, power_at=lambda n: 0.9)
    assert sum(r2["stages"].values()) == 1001 and r2["max_before_confirm"] == 901
    for bad in ((50, 20, 20), (-10, 60, 50)):
        with pytest.raises(ValueError):
            stats.plan_split(100, bad, 10, lambda n: 0.5)


def test_cli_plan_verdicts(capsys):
    main(["plan", "--n-total", "300", "--delta", "0.01", "--sd", "0.085"])
    out = capsys.readouterr().out
    assert "not enough data" in out and "prospective" in out
    main(["plan", "--n-total", "20000", "--delta", "0.01", "--sd", "0.085"])
    assert "Verdict: enough" in capsys.readouterr().out
    main(["plan", "--n-total", "1500", "--delta", "0.01", "--sd", "0.085", "--split", "50", "20", "30"])
    assert "not with this split" in capsys.readouterr().out
    main(["plan", "--n-total", "500", "--rates", "0.7", "0.8"])
    assert "per group" in capsys.readouterr().out
    main(["plan", "--delta", "0.01", "--sd", "0.085"])                     # no data size: only what is needed
    assert "needs about" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["plan", "--n-total", "100"])
