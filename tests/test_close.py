import random
import pytest
from forecastseal import Ledger, LedgerError, report
from forecastseal.cli import main

MP = {"name": "c", "kind": "measure", "metric": "q", "direction": "higher_is_better", "n_target": 20, "alpha": 0.05}
FP = {"name": "f", "metric": "log_loss", "n_target": 10, "alpha": 0.05}


def measure_study(tmp_path, n=8):
    l = Ledger(tmp_path / ".fseal"); l.init()
    h = l.register(MP)["hash"]
    rng = random.Random(1)
    l.measure_many(h, [{"item": f"d{i}", "system": s, "value": rng.random() + (0.2 if s == "v2" else 0)} for i in range(n) for s in ("v1", "v2")])
    return l, h


def test_close_early_records_the_reason_and_defaults_the_kind(tmp_path):
    l, h = measure_study(tmp_path)
    e = l.close(h, "ran out of time")
    assert e["body"]["kind"] == "stopped_early" and e["body"]["n_complete"] == 8 and e["body"]["n_target"] == 20
    assert l.verify() == [] and l.status()["closed_studies"] == 1


def test_a_closed_study_takes_no_more_data_and_cannot_close_twice(tmp_path):
    l, h = measure_study(tmp_path)
    l.close(h, "stopped")
    with pytest.raises(LedgerError):
        l.measure("d99", "v1", 0.5, h)
    with pytest.raises(LedgerError):
        l.measure_many(h, [{"item": "d98", "system": "v1", "value": 0.4}])
    with pytest.raises(LedgerError):
        l.close(h, "again")


def test_completed_needs_the_planned_size(tmp_path):
    l, h = measure_study(tmp_path, n=8)
    with pytest.raises(LedgerError):
        l.close(h, "done", kind="completed")
    l.close(h, "gave up", kind="abandoned")


def test_reason_is_validated(tmp_path):
    l, h = measure_study(tmp_path)
    for bad in ("", "   ", "bad\x1b[31m", "x" * 300):
        with pytest.raises(LedgerError):
            l.close(h, bad)


def test_verify_flags_data_added_after_closure_by_hand(tmp_path):
    l, h = measure_study(tmp_path)
    l.close(h, "stopped")
    l._append("measurement", {"id": "v1::late", "item": "late", "system": "v1", "protocol": h, "value": 1.0})
    assert any("after the study was closed" in p for p in l.verify())


def test_forecast_study_can_still_resolve_after_closing(tmp_path):
    l = Ledger(tmp_path / ".fseal"); l.init()
    h = l.register(FP)["hash"]
    l.predict("p1", h, "me", {"y": 0.6, "n": 0.4}, event="e1")
    l.close(h, "stopping new questions", kind="stopped_early")
    with pytest.raises(LedgerError):
        l.predict("p2", h, "me", {"y": 0.6, "n": 0.4}, event="e2")
    l.resolve("e1", "y")                                         # an earlier question can still be answered
    assert l.verify() == []


def test_report_says_what_an_early_stop_can_and_cannot_tell(tmp_path):
    l, h = measure_study(tmp_path)
    l.close(h, "ran out of time")
    page = report.build(l, h)
    assert "This study ended early" in page and "ran out of time" in page and "cannot say" in page and "narrower" in page
    assert "stopped early" in page and "<script" not in page.lower()


def test_report_for_a_completed_study(tmp_path):
    l, h = measure_study(tmp_path, n=20)
    l.close(h, "finished as planned")
    page = report.build(l, h)
    assert "Study closed" in page and "This study ended early" not in page


def test_cli_close(tmp_path, capsys):
    l, h = measure_study(tmp_path)
    main(["--dir", str(l.root), "close", "--reason", "ran out of time"])
    out = capsys.readouterr().out
    assert "stopped_early at 8 of 20" in out and "hints, not a result" in out
    with pytest.raises(SystemExit):
        main(["--dir", str(l.root), "close", "--reason", "again"])
