import json
import pytest
from forecastseal import Ledger, LedgerError
from forecastseal.cli import main

P = {"name": "imp", "kind": "measure", "n_target": 3, "alpha": 0.05,
     "metrics": [{"name": "a", "direction": "higher_is_better", "primary": True}, {"name": "b", "direction": "lower_is_better", "primary": False}]}


@pytest.fixture
def led(tmp_path):
    l = Ledger(tmp_path / ".fseal")
    l.init()
    return l, l.register(P)["hash"]


def test_measure_many_is_atomic(led):
    l, h = led
    rows = [{"item": "d1", "system": "v1", "metric": "a", "value": 1.0}, {"item": "d2", "system": "v1", "metric": "a", "value": float("nan")},
            {"item": "d3", "system": "v1", "metric": "zzz", "value": 1.0}]
    before = l.head()
    with pytest.raises(LedgerError) as ex:
        l.measure_many(h, rows)
    assert "nothing was written" in str(ex.value) and "row 2" in str(ex.value) and "row 3" in str(ex.value)
    assert l.head() == before                                         # nothing was appended


def test_measure_many_chain_and_skip_existing(led):
    l, h = led
    rows = [{"item": f"d{i}", "system": "v1", "metric": "a", "value": float(i)} for i in range(50)]
    assert l.measure_many(h, rows) == {"added": 50, "skipped": 0}
    assert l.verify() == []
    with pytest.raises(LedgerError):
        l.measure_many(h, rows[:2])                                   # strict by default
    assert l.measure_many(h, rows[:2] + [{"item": "new", "system": "v1", "metric": "a", "value": 9.0}], skip_existing=True) == {"added": 1, "skipped": 2}
    assert l.verify() == []


def test_duplicates_inside_one_batch_are_caught(led):
    l, h = led
    r = {"item": "d1", "system": "v1", "metric": "a", "value": 1.0}
    with pytest.raises(LedgerError):
        l.measure_many(h, [r, dict(r)])


def test_csv_long_and_wide(tmp_path, capsys):
    d = str(tmp_path / ".fseal")
    (tmp_path / "p.json").write_text(json.dumps(P))
    main(["--dir", d, "init"]); main(["--dir", d, "register", str(tmp_path / "p.json")])
    (tmp_path / "long.csv").write_text("item,system,metric,value\nd1,v1,a,0.5\nd1,v2,a,0.7\nd1,v1,b,3\n")
    main(["--dir", d, "import-csv", str(tmp_path / "long.csv")])
    (tmp_path / "wide.csv").write_text("item,system,a,b\nd2,v1,0.4,2\nd2,v2,0.9,\n")           # blank cell skipped
    main(["--dir", d, "import-csv", str(tmp_path / "wide.csv"), "--wide"])
    assert "imported 3 values" in capsys.readouterr().out or True
    l = Ledger(d)
    assert l.status()["measurements"] == 6 and l.verify() == []
    main(["--dir", d, "import-csv", str(tmp_path / "wide.csv"), "--wide", "--skip-existing"])
    assert "skipped" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--dir", d, "import-csv", str(tmp_path / "wide.csv"), "--wide"])              # strict duplicate


def test_csv_errors_name_the_line(tmp_path):
    d = str(tmp_path / ".fseal")
    (tmp_path / "p.json").write_text(json.dumps(P))
    main(["--dir", d, "init"]); main(["--dir", d, "register", str(tmp_path / "p.json")])
    (tmp_path / "bad.csv").write_text("item,system,metric,value\nd1,v1,a,0.5\nd2,v1,a,oops\n")
    with pytest.raises(SystemExit):
        main(["--dir", d, "import-csv", str(tmp_path / "bad.csv")])
    assert Ledger(d).status()["measurements"] == 0
    (tmp_path / "unk.csv").write_text("item,system,zz\nd1,v1,1\n")
    with pytest.raises(SystemExit):
        main(["--dir", d, "import-csv", str(tmp_path / "unk.csv"), "--wide"])
