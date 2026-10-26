import json
import random
import pytest
from forecastseal import Ledger, LedgerError, report, workflow
from forecastseal.cli import main

METRICS = [{"name": "errors", "direction": "lower_is_better", "primary": True},
           {"name": "coverage", "direction": "higher_is_better", "primary": True},
           {"name": "style", "direction": "higher_is_better", "primary": False}]
P = {"name": "multi", "kind": "measure", "metrics": METRICS, "n_target": 30, "alpha": 0.05, "n_comparisons": 1}


@pytest.fixture
def led(tmp_path):
    l = Ledger(tmp_path / ".fseal")
    l.init()
    return l


def fill(led, h, n=30, seed=3):
    rng = random.Random(seed)
    for i in range(n):
        base = rng.gauss(0, 1)
        for sys_, e_gap, c_gap, s_gap in (("v1", 0.0, 0.0, 0.0), ("v2", -0.6, 0.5, 0.0)):
            led.measure(f"d{i}", sys_, 3 + base * 0.3 + e_gap + rng.gauss(0, 0.2), h, metric="errors")
            led.measure(f"d{i}", sys_, 0.5 + base * 0.1 + c_gap * 0.2 + rng.gauss(0, 0.05), h, metric="coverage")
            led.measure(f"d{i}", sys_, 0.5 + base * 0.1 + s_gap + rng.gauss(0, 0.05), h, metric="style")


def test_protocol_validation(led):
    for bad in ({**P, "metrics": []}, {**P, "metrics": "x"}, {**P, "metrics": [{"name": "a", "direction": "up", "primary": True}]},
                {**P, "metrics": [{"name": "a", "direction": "higher_is_better"}, {"name": "b", "direction": "higher_is_better"}]},   # no primary
                {**P, "metrics": [METRICS[0], METRICS[0]]}, {**P, "metrics": [{**METRICS[0], "primary": "yes"}]}):
        with pytest.raises(LedgerError):
            led.register(bad)
    led.register(P)


def test_measure_needs_a_known_metric(led):
    h = led.register(P)["hash"]
    with pytest.raises(LedgerError):
        led.measure("d1", "v1", 1.0, h)                              # several metrics: must name one
    with pytest.raises(LedgerError):
        led.measure("d1", "v1", 1.0, h, metric="nope")
    led.measure("d1", "v1", 1.0, h, metric="errors")
    led.measure("d1", "v1", 0.9, h, metric="coverage")               # same item and system, another metric: fine
    with pytest.raises(LedgerError):
        led.measure("d1", "v1", 2.0, h, metric="errors")             # same metric: no overwrite
    assert led.verify() == []


def test_family_size_and_directions(led):
    h = led.register(P)["hash"]
    fill(led, h)
    r_err = workflow.compare_logged(led, h, "v2", "v1", metric="errors")
    r_cov = workflow.compare_logged(led, h, "v2", "v1", metric="coverage")
    r_sty = workflow.compare_logged(led, h, "v2", "v1", metric="style")
    assert r_err["family"] == 2 and r_cov["family"] == 2 and r_sty["family"] == 1
    assert r_err["alpha_adj"] == pytest.approx(0.025) and r_sty["alpha_adj"] == pytest.approx(0.05)
    assert r_err["better"] == "v2" and r_err["mean_diff"] < 0          # fewer errors is better
    assert r_cov["better"] == "v2" and r_cov["mean_diff"] > 0          # more coverage is better
    assert not r_sty["excludes_zero"]                                  # no true difference in the exploratory metric


def test_looks_are_counted_per_metric(led):
    h = led.register(P)["hash"]
    fill(led, h)
    workflow.compare_logged(led, h, "v2", "v1", metric="errors")
    second = workflow.compare_logged(led, h, "v2", "v1", metric="errors")
    first_other = workflow.compare_logged(led, h, "v2", "v1", metric="coverage")
    assert second["prior_final"] == 1 and first_other["prior_final"] == 0


def test_tampering_with_a_metric_name_is_detected(led):
    h = led.register(P)["hash"]
    led.measure("d1", "v1", 1.0, h, metric="errors")
    led._append("measurement", {"id": "x", "item": "d1", "system": "v1", "protocol": h, "value": 1.0, "metric": "bogus"})
    assert any("unknown or missing metric" in p for p in led.verify())


def test_single_metric_protocols_still_work(led):
    h = led.register({"name": "one", "kind": "measure", "metric": "score", "direction": "higher_is_better", "n_target": 5, "alpha": 0.05})["hash"]
    led.measure("d1", "a", 0.5, h)                                   # no metric name needed
    assert led.items_for(h)[0]["value"] == 0.5


def test_report_shows_summary_and_roles(led):
    h = led.register(P)["hash"]
    fill(led, h)
    page = report.build(led, h, compare=[("v2", "v1")])
    assert "Summary" in page and "primary" in page and "exploratory" in page and "Confirmatory family" in page
    assert "<script" not in page.lower() and page.count("<svg") >= 6


def test_cli_all_metrics(tmp_path, capsys):
    d = str(tmp_path / ".fseal")
    (tmp_path / "p.json").write_text(json.dumps(P))
    main(["--dir", d, "init"]); main(["--dir", d, "register", str(tmp_path / "p.json")])
    h = Ledger(d).head()
    lines = []
    rng = random.Random(4)
    for i in range(30):
        for s, g in (("v1", 0.0), ("v2", 0.5)):
            for m in ("errors", "coverage", "style"):
                lines.append(json.dumps({"item": f"d{i}", "system": s, "metric": m, "value": rng.gauss(g if m != "errors" else -g, 0.3)}))
    f = tmp_path / "m.jsonl"; f.write_text("\n".join(lines))
    main(["--dir", d, "measure", "--file", str(f)])
    main(["--dir", d, "score"])
    assert "[primary]" in capsys.readouterr().out
    main(["--dir", d, "test", "v2", "v1"])                            # every metric
    out = capsys.readouterr().out
    assert out.count("paired items") == 3 and "[exploratory" in out
    with pytest.raises(SystemExit):
        main(["--dir", d, "measure", "--item", "x", "--system", "v1", "--value", "1"])   # metric required


def test_report_counts_the_analyses_it_just_logged(led):
    h = led.register(P)["hash"]
    fill(led, h)
    page = report.build(led, h, compare=[("v2", "v1")])
    assert "<b>Analyses logged</b><span>3</span>" in page


def test_report_does_not_abort_for_an_incomplete_metric(led):
    h = led.register(P)["hash"]
    fill(led, h)
    rng = random.Random(9)
    led2 = led
    # a fourth, incomplete situation: drop to a protocol where one metric has no data at all
    p2 = {**P, "name": "partial", "metrics": METRICS + [{"name": "later", "direction": "higher_is_better", "primary": False}]}
    h2 = led2.register(p2)["hash"]
    for i in range(30):
        for s in ("v1", "v2"):
            for m in ("errors", "coverage", "style"):
                led2.measure(f"d{i}", s, rng.random(), h2, metric=m)
    page = report.build(led2, h2, compare=[("v2", "v1")])
    assert "Comparison not run" in page and "nothing recorded" in page
    assert page.count("final analysis") >= 3                     # the three complete metrics still ran
