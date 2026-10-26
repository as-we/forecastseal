import json
import pytest
from forecastseal import Ledger, LedgerError, report
from forecastseal.cli import main

MP = {"name": "m", "kind": "measure", "metric": "score", "direction": "higher_is_better", "n_target": 3, "alpha": 0.05}


@pytest.fixture
def led(tmp_path):
    l = Ledger(tmp_path / ".fseal")
    l.init()
    return l


def test_manifest_hash_ignores_order_and_detects_change():
    a = Ledger.manifest_of(["d3", "d1", "d2"])
    assert a == Ledger.manifest_of(["d1", "d2", "d3"]) and a["count"] == 3
    assert a["sha256"] != Ledger.manifest_of(["d1", "d2", "d4"])["sha256"]
    for bad in ([], ["a", "a"], ["bad\x1b"], "text"):
        with pytest.raises(LedgerError):
            Ledger.manifest_of(bad)


def test_register_seals_the_manifest_and_limits_n_target(led):
    h = led.register(MP, manifest_ids=["d1", "d2", "d3", "d4"])["hash"]
    assert led.protocols()[h]["body"]["manifest"]["count"] == 4
    with pytest.raises(LedgerError):
        led.register({**MP, "name": "big", "n_target": 9}, manifest_ids=["d1", "d2"])


def test_check_manifest_flags_items_outside_the_sealed_set(led):
    ids = ["d1", "d2", "d3"]
    h = led.register(MP, manifest_ids=ids)["hash"]
    led.measure("d1", "v1", 0.5, h)
    led.measure("x9", "v1", 0.5, h)                                   # recorded, but never in the set
    probs = led.check_manifest(ids)
    assert len(probs) == 1 and "x9" in probs[0]
    assert led.check_manifest(["d1", "d2"])[0].startswith("no protocol was sealed")   # a different set


def test_cli_manifest_roundtrip(tmp_path, capsys):
    d = str(tmp_path / ".fseal")
    (tmp_path / "p.json").write_text(json.dumps(MP))
    (tmp_path / "items.txt").write_text("d1\nd2\nd3\n")
    main(["--dir", d, "init"])
    main(["--dir", d, "register", str(tmp_path / "p.json"), "--manifest", str(tmp_path / "items.txt")])
    assert "sealed item set: 3 items" in capsys.readouterr().out
    h = Ledger(d).head()
    main(["--dir", d, "measure", "--item", "d1", "--system", "v1", "--value", "0.5", "--protocol", h])
    main(["--dir", d, "verify", "--manifest", str(tmp_path / "items.txt")])
    (tmp_path / "other.json").write_text(json.dumps(["d1", "d2", "dX"]))
    with pytest.raises(SystemExit) as ex:
        main(["--dir", d, "verify", "--manifest", str(tmp_path / "other.json")])
    assert ex.value.code == 1


def test_report_shows_the_manifest(led):
    h = led.register(MP, manifest_ids=["d1", "d2", "d3"])["hash"]
    led.measure("d1", "v1", 0.4, h)
    assert "Sealed item set" in report.build(led, h)
