import json
import re
import pytest
from forecastseal import Ledger, LedgerError, report
from forecastseal.cli import main

PROTO = {"name": "demo <b>x</b>", "metric": "log_loss", "n_target": 20, "alpha": 0.05, "n_comparisons": 1}


def make(tmp_path, n=20, names=("A", "B")):
    led = Ledger(tmp_path / ".fseal")
    led.init()
    h = led.register(PROTO)["hash"]
    for i in range(n):
        for k, who in enumerate(names):
            p = 0.55 + 0.1 * k
            led.predict(f"{who}{i}", h, who, {"yes": p, "no": 1 - p}, event=f"e{i}")
        led.resolve(f"e{i}", "yes" if i % 3 else "no")
    return led, h


def test_report_is_self_contained_and_escaped(tmp_path):
    led, h = make(tmp_path)
    page = report.build(led, h, now="2026-01-01T00:00:00+00:00")
    assert "<script" not in page.lower() and "http://" not in page and "https://" not in page
    assert "Content-Security-Policy" in page and "default-src 'none'" in page
    assert "demo <b>x</b>" not in page and "demo &lt;b&gt;x&lt;/b&gt;" in page          # user text is escaped
    assert "intact" in page and h in page and "Calibration" in page
    assert page.count("<svg") >= 3


def test_hostile_forecaster_name_cannot_inject_markup(tmp_path):
    led = Ledger(tmp_path / ".fseal")
    led.init()
    h = led.register({**PROTO, "name": "ok"})["hash"]
    evil = '"><img src=x onerror=alert(1)>'
    led.predict("a", h, evil, {"yes": 0.6, "no": 0.4}, event="e")
    led.resolve("e", "yes")
    page = report.build(led, h)
    assert "<img" not in page and "&lt;img" in page


def test_broken_ledger_is_flagged_in_the_report(tmp_path):
    led, h = make(tmp_path)
    lines = led.path.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[3]); e["body"]["probs"] = {"yes": 0.99, "no": 0.01}
    lines[3] = json.dumps(e, sort_keys=True)
    led.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    page = report.build(led, h)
    assert "BROKEN" in page and "Do not trust" in page


def test_comparison_rules_apply_to_the_report(tmp_path):
    led, h = make(tmp_path, n=10)                                   # 10 of 20 planned
    with pytest.raises(LedgerError):
        report.build(led, h, compare=[("A", "B")])
    page = report.build(led, h, compare=[("A", "B")], interim=True)
    assert "INTERIM LOOK" in page and "no verdict" in page
    assert led.status()["analyses"] == 1                             # the look was logged


def test_final_comparison_and_extra_look_warning(tmp_path):
    led, h = make(tmp_path, n=20)
    page = report.build(led, h, compare=[("A", "B")])
    assert "final analysis" in page and ("interval excludes 0" in page or "interval includes 0" in page)
    page2 = report.build(led, h, compare=[("A", "B")])
    assert "planned 1 comparison" in page2                           # second final look is flagged


def test_cli_writes_the_file(tmp_path, capsys):
    make(tmp_path)
    out = tmp_path / "r.html"
    main(["--dir", str(tmp_path / ".fseal"), "report", "-o", str(out), "--compare", "A", "B"])
    assert out.exists() and "forecastseal report" in out.read_text(encoding="utf-8")
    assert "self-contained" in capsys.readouterr().out
