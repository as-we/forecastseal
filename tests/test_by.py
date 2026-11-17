"""Splitting by group or by a meta key: descriptive tables and exploratory, logged comparisons."""
import pytest

from forecastseal import Ledger, LedgerError, report, workflow
from forecastseal.cli import main

MP = {"name": "m", "kind": "measure", "metric": "score", "direction": "higher_is_better", "n_target": 4, "alpha": 0.05}


@pytest.fixture
def led(tmp_path):
    l = Ledger(tmp_path / ".fseal")
    l.init()
    return l


def fill(led, h):
    rows = []
    for i, cond in enumerate(["jpeg", "jpeg", "crop", "crop"]):
        rows.append({"item": f"d{i}", "system": "new", "value": 0.9 - 0.1 * i, "meta": {"condition": cond}, "group": f"g{i % 2}"})
        rows.append({"item": f"d{i}", "system": "old", "value": 0.5, "meta": {"condition": cond}, "group": f"g{i % 2}"})
    rows.append({"item": "d9", "system": "new", "value": 0.1})               # no meta, no group
    led.measure_many(h, rows)


def test_strata_by_meta_and_group(led):
    h = led.register(MP)["hash"]
    fill(led, h)
    rows = led.items_for(h)
    by_cond = workflow.strata(rows, "condition")
    assert list(by_cond) == ["(none)", "crop", "jpeg"] and len(by_cond["jpeg"]) == 4
    assert list(workflow.strata(rows, "group")) == ["(none)", "g0", "g1"]


def test_compare_by_is_exploratory_and_logged(led):
    h = led.register(MP)["hash"]
    fill(led, h)
    res = workflow.compare_by(led, h, "new", "old", "condition")
    got = {r["stratum"]: r for r in res}
    assert got["jpeg"]["n"] == 2 and got["jpeg"]["mean_diff"] == pytest.approx(0.35)
    assert got["(none)"]["n"] == 0                                         # "old" has nothing there: skipped, not an error
    logged = [e for e in led.entries() if e["type"] == "analysis"]
    assert [e["body"]["kind"] for e in logged] == ["exploratory", "exploratory"]
    assert "condition = crop" in logged[0]["body"]["what"]
    assert led.verify() == []


def test_cli_score_test_and_report_by(led, capsys, tmp_path):
    h = led.register(MP)["hash"]
    fill(led, h)
    d = str(led.root)
    main(["--dir", d, "score", "--by", "condition"])
    out = capsys.readouterr().out
    assert "condition = crop" in out and "descriptive only" in out
    main(["--dir", d, "test", "new", "old", "--by", "group"])
    out = capsys.readouterr().out
    assert "EXPLORATORY" in out and "g0" in out and "no verdicts" in out
    page = report.build(led, h, by="condition")
    assert "By condition (descriptive)" in page and "3 subgroups" in page
    assert "Timeline of looks" not in page                                 # exploratory looks are not final or interim looks


def test_stages_work_for_forecast_protocols(led):
    fp = {"name": "f", "metric": "brier", "n_target": 1, "alpha": 0.05}
    ex = led.register({**fp, "name": "explore", "stage": "explore"})["hash"]
    led.predict("p1", ex, "me", {"yes": 0.6, "no": 0.4}, event="e1")
    cf = led.register({**fp, "name": "confirm", "stage": "confirm", "after": ex, "systems": ["me"]})["hash"]
    with pytest.raises(LedgerError, match="already used in another stage"):
        led.predict("p2", cf, "me", {"yes": 0.6, "no": 0.4}, event="e1")
    with pytest.raises(LedgerError, match="not one of the candidates"):
        led.predict("p3", cf, "you", {"yes": 0.6, "no": 0.4}, event="e2")
    led.predict("p4", cf, "me", {"yes": 0.6, "no": 0.4}, event="e2")
    assert led.verify() == []
