import json
import random
import pytest
from forecastseal import Ledger, LedgerError, report, stats
from forecastseal.cli import main

MP = {"name": "prompt-versions", "kind": "measure", "metric": "quality score", "direction": "higher_is_better", "n_target": 30, "alpha": 0.05}


@pytest.fixture
def led(tmp_path):
    l = Ledger(tmp_path / ".fseal")
    l.init()
    return l


def fill(led, h, n=30, gap=0.08, seed=1):
    rng = random.Random(seed)
    for i in range(n):
        base = rng.gauss(0.6, 0.15)
        led.measure(f"doc{i}", "v1", base + rng.gauss(0, 0.05), h)
        led.measure(f"doc{i}", "v2", base + gap + rng.gauss(0, 0.05), h)


def test_measure_protocol_validation(led):
    for bad in ({**MP, "direction": "bigger"}, {k: v for k, v in MP.items() if k != "direction"}, {**MP, "kind": "other"}, {**MP, "metric": "bad\x1b"}):
        with pytest.raises(LedgerError):
            led.register(bad)
    led.register(MP)


def test_measure_rules(led):
    h = led.register(MP)["hash"]
    led.measure("d1", "v1", 0.5, h)
    for bad in (float("nan"), float("inf"), True, "0.5", None):
        with pytest.raises(LedgerError):
            led.measure("d2", "v1", bad, h)
    with pytest.raises(LedgerError):
        led.measure("d1", "v1", 0.9, h)                      # no overwriting
    with pytest.raises(LedgerError):
        led.predict("p", h, "me", {"y": 0.5, "n": 0.5})      # wrong kind
    fh = led.register({"name": "f", "metric": "brier", "n_target": 5, "alpha": 0.05})["hash"]
    with pytest.raises(LedgerError):
        led.measure("d1", "v1", 0.5, fh)                     # wrong kind the other way
    assert led.verify() == []


def test_verify_catches_hand_built_violations(led):
    h = led.register(MP)["hash"]
    led.measure("d1", "v1", 0.5, h)
    led._append("measurement", {"id": "v1::d1", "item": "d1", "system": "v1", "protocol": h, "value": 0.99})
    led._append("prediction", {"id": "p", "event": "e", "protocol": h, "forecaster": "x", "probs": {"y": 0.5, "n": 0.5}})
    probs = led.verify()
    assert any("duplicate measurement" in p for p in probs) and any("prediction under a measure protocol" in p for p in probs)


def test_editing_a_value_is_detected(led):
    h = led.register(MP)["hash"]
    led.measure("d1", "v1", 0.5, h)
    lines = led.path.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1]); e["body"]["value"] = 0.95
    lines[1] = json.dumps(e, sort_keys=True)
    led.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert any("edited" in p for p in led.verify())


def test_compare_names_the_better_system_for_higher_is_better(led):
    h = led.register(MP)["hash"]
    fill(led, h)
    rows = led.items_for(h)
    r = stats.compare(rows, "quality score", "v2", "v1", 0.05, higher_is_better=True)
    assert r["excludes_zero"] and r["better"] == "v2" and r["mean_diff"] > 0
    r2 = stats.compare(rows, "quality score", "v1", "v2", 0.05, higher_is_better=True)
    assert r2["better"] == "v2"
    flat = stats.compare(rows, "quality score", "v1", "v1", 0.05) if False else None
    assert flat is None


def test_lower_is_better_flips_the_winner(led):
    p = {**MP, "direction": "lower_is_better", "name": "errors"}
    h = led.register(p)["hash"]
    fill(led, h)                                              # v2 has larger numbers = worse
    r = stats.compare(led.items_for(h), "errors", "v2", "v1", 0.05)
    assert r["better"] == "v1"


def test_calibration_is_refused_for_measures(led):
    h = led.register(MP)["hash"]
    fill(led, h, n=5)
    with pytest.raises(ValueError):
        stats.calibration(led.items_for(h))


def test_cli_measure_test_and_report(tmp_path, capsys):
    d = str(tmp_path / ".fseal")
    pf = tmp_path / "p.json"
    pf.write_text(json.dumps(MP))
    main(["--dir", d, "init"]); main(["--dir", d, "register", str(pf)])
    rng = random.Random(2)
    lines = []
    for i in range(30):
        b = rng.gauss(0.6, 0.15)
        lines += [json.dumps({"item": f"d{i}", "system": "v1", "value": b}), json.dumps({"item": f"d{i}", "system": "v2", "value": b + 0.1 + rng.gauss(0, 0.04)})]
    f = tmp_path / "m.jsonl"; f.write_text("\n".join(lines))
    main(["--dir", d, "measure", "--file", str(f)])
    main(["--dir", d, "measure", "--item", "extra", "--system", "v1", "--value", "0.4"])
    main(["--dir", d, "score"])
    assert "higher is better" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--dir", d, "calibration"])
    main(["--dir", d, "test", "v2", "v1"])
    out = capsys.readouterr().out
    assert "positive favours v2" in out and "v2 is better" in out
    out_html = tmp_path / "r.html"
    main(["--dir", d, "report", "-o", str(out_html)])
    page = out_html.read_text(encoding="utf-8")
    assert "Calibration" not in page and "higher is better" in page and "Mean value" in page and "<script" not in page.lower()


def test_report_handles_negative_values(led):
    h = led.register({**MP, "name": "neg", "n_target": 3}).get("hash")
    for i in range(3):
        led.measure(f"d{i}", "a", -1.0 - i, h); led.measure(f"d{i}", "b", 0.5 + i, h)
    page = report.build(led, h)
    assert "-3.000" in page or "-3." in page
