import json
import math
import random
import pytest
from forecastseal import Ledger, LedgerError, stats, workflow, report
from forecastseal.cli import main


def test_kappa_known_values():
    a = [1, 1, 0, 0, 1, 0, 1, 0]
    assert stats.cohen_kappa(a, a) == pytest.approx(1.0)
    assert stats.cohen_kappa(a, [1 - x for x in a]) == pytest.approx(-1.0)
    # 2x2 table with 100 items: observed agreement 0.70; kappa follows from the marginals
    x = [1] * 20 + [1] * 5 + [0] * 25 + [0] * 50        # a
    y = [1] * 20 + [0] * 5 + [1] * 25 + [0] * 50        # b
    k = stats.cohen_kappa(x, y)
    po = 70 / 100
    pe = (0.25 * 0.45) + (0.75 * 0.55)
    assert k == pytest.approx((po - pe) / (1 - pe))


def test_weighted_kappa_forgives_near_misses():
    a = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
    b = [1, 2, 3, 4, 4, 1, 2, 3, 5, 5]                   # two off-by-one disagreements
    assert stats.cohen_kappa(a, b, "quadratic") > stats.cohen_kappa(a, b, "linear") > stats.cohen_kappa(a, b, "none")
    with pytest.raises(ValueError):
        stats.cohen_kappa(a, b, "cubic")
    with pytest.raises(ValueError):
        stats.cohen_kappa([], [])


def test_ac1_is_steadier_than_kappa_when_one_label_dominates():
    a = [1] * 96 + [0] * 4
    b = [1] * 94 + [0] * 2 + [1] * 2 + [0] * 2        # 96% agreement but very skewed
    r = stats.agreement(a, b)
    assert r["top_label_share"] > 0.9 and r["ac1"] > r["kappa"] and r["observed"] == pytest.approx(0.96)


def test_agreement_interval_contains_the_estimate():
    rng = random.Random(2)
    a = [rng.randint(0, 2) for _ in range(120)]
    b = [x if rng.random() < 0.7 else rng.randint(0, 2) for x in a]
    r = stats.agreement(a, b)
    assert r["ci"][0] < r["kappa"] < r["ci"][1]
    assert r == stats.agreement(a, b)                        # reproducible


def _ledger_with_labels(tmp_path):
    l = Ledger(tmp_path / ".fseal"); l.init()
    h = l.register({"name": "judge", "kind": "measure", "metric": "label", "direction": "higher_is_better", "n_target": 5, "alpha": 0.05})["hash"]
    rng = random.Random(5)
    rows = []
    for i in range(40):
        human = rng.randint(1, 5)
        llm = human if rng.random() < 0.7 else min(5, max(1, human + rng.choice([-1, 1])))
        rows += [{"item": f"d{i}", "system": "human", "value": float(human)}, {"item": f"d{i}", "system": "llm", "value": float(llm)}]
    l.measure_many(h, rows)
    return l, h


def test_cli_agreement(tmp_path, capsys):
    l, h = _ledger_with_labels(tmp_path)
    main(["--dir", str(l.root), "agreement", "human", "llm", "--weights", "quadratic"])
    out = capsys.readouterr().out
    assert "Cohen's kappa" in out and "Gwet's AC1" in out and "confusion" in out
    assert l.status()["analyses"] == 1                      # the look is logged
    with pytest.raises(SystemExit):
        main(["--dir", str(l.root), "agreement", "human", "nobody"])


def test_agreement_refuses_non_integer_labels(tmp_path):
    l = Ledger(tmp_path / ".fseal"); l.init()
    h = l.register({"name": "x", "kind": "measure", "metric": "score", "direction": "higher_is_better", "n_target": 3, "alpha": 0.05})["hash"]
    l.measure_many(h, [{"item": f"d{i}", "system": s, "value": 0.5 + i * 0.1} for i in range(3) for s in ("a", "b")])
    with pytest.raises(SystemExit):
        main(["--dir", str(l.root), "agreement", "a", "b"])


# ---------------- non-inferiority ----------------
def _ni_rows(gap, n=80, seed=1):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        base = rng.gauss(0.7, 0.1)
        rows += [{"forecaster": "cheap", "event": f"d{i}", "value": base + gap + rng.gauss(0, 0.03)},
                 {"forecaster": "big", "event": f"d{i}", "value": base + rng.gauss(0, 0.03)}]
    return rows


def test_non_inferior_when_the_gap_is_inside_the_margin():
    r = stats.compare(_ni_rows(-0.005), "q", "cheap", "big", 0.05, higher_is_better=True, margin=0.03)
    assert r["non_inferior"] is True and r["margin"] == 0.03


def test_not_non_inferior_when_clearly_worse():
    r = stats.compare(_ni_rows(-0.06), "q", "cheap", "big", 0.05, higher_is_better=True, margin=0.03)
    assert r["non_inferior"] is False


def test_lower_is_better_direction_for_the_margin():
    rows = _ni_rows(0.005)                                   # cheap has slightly larger (worse) values
    assert stats.compare(rows, "err", "cheap", "big", 0.05, higher_is_better=False, margin=0.03)["non_inferior"] is True
    assert stats.compare(_ni_rows(0.08), "err", "cheap", "big", 0.05, higher_is_better=False, margin=0.03)["non_inferior"] is False


def test_no_margin_means_no_claim():
    assert stats.compare(_ni_rows(0.0), "q", "cheap", "big", 0.05, higher_is_better=True)["non_inferior"] is None


def test_margin_is_sealed_and_validated(tmp_path):
    l = Ledger(tmp_path / ".fseal"); l.init()
    base = {"name": "ni", "kind": "measure", "n_target": 5, "alpha": 0.05}
    for bad in (0, -1, "0.1", True, float("nan")):
        with pytest.raises(LedgerError):
            l.register({**base, "metric": "q", "direction": "higher_is_better", "margin": bad})
        with pytest.raises(LedgerError):
            l.register({**base, "metrics": [{"name": "q", "direction": "higher_is_better", "primary": True, "margin": bad}]})
    h = l.register({**base, "metric": "q", "direction": "higher_is_better", "margin": 0.03})["hash"]
    assert workflow.metrics_of(l, h)[0]["margin"] == 0.03


def test_workflow_and_report_show_the_margin(tmp_path):
    l = Ledger(tmp_path / ".fseal"); l.init()
    h = l.register({"name": "ni", "kind": "measure", "metric": "q", "direction": "higher_is_better", "n_target": 80, "alpha": 0.05, "margin": 0.03})["hash"]
    rows = [{"item": r["event"], "system": r["forecaster"], "value": r["value"]} for r in _ni_rows(-0.005)]
    l.measure_many(h, rows)
    res = workflow.compare_logged(l, h, "cheap", "big")
    assert res["non_inferior"] is True
    page = report.build(l, h, compare=[("cheap", "big")], interim=True)
    assert "Non-inferiority (margin 0.03" in page
