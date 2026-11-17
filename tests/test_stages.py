"""Stages (explore / validate / confirm): an item, or a group, is used by one stage of a chain only."""
import json

import pytest

from forecastseal import Ledger, LedgerError, report
from forecastseal.cli import main

BASE = {"kind": "measure", "metric": "score", "direction": "higher_is_better", "n_target": 2, "alpha": 0.05}


@pytest.fixture
def led(tmp_path):
    l = Ledger(tmp_path / ".fseal")
    l.init()
    return l


def proto(name, **kw):
    return {**BASE, "name": name, **kw}


def test_stage_values_and_after_rules(led):
    with pytest.raises(LedgerError, match="stage must be"):
        led.register(proto("x", stage="final"))
    with pytest.raises(LedgerError, match='needs a "stage"'):
        led.register(proto("x", after="0" * 64))
    ex = led.register(proto("explore", stage="explore"))["hash"]
    with pytest.raises(LedgerError, match="unknown protocol"):
        led.register(proto("c", stage="confirm", after="f" * 64))
    with pytest.raises(LedgerError, match="same protocol twice"):
        led.register(proto("c", stage="confirm", after=[ex, ex]))
    cf = led.register(proto("confirm", stage="confirm", after=ex))["hash"]
    with pytest.raises(LedgerError, match="cannot come after"):
        led.register(proto("late explore", stage="explore", after=cf))
    plain = led.register(proto("no stage"))["hash"]
    with pytest.raises(LedgerError, match="has no stage"):
        led.register(proto("v", stage="validate", after=plain))


def test_an_item_is_used_by_one_stage_only(led):
    ex = led.register(proto("explore", stage="explore"))["hash"]
    led.measure("d1", "v1", 0.5, ex)
    led.measure("d1", "v2", 0.6, ex)                     # the same item for another system in the same stage is fine
    cf = led.register(proto("confirm", stage="confirm", after=ex))["hash"]
    with pytest.raises(LedgerError, match="already used in another stage"):
        led.measure("d1", "v2", 0.7, cf)
    with pytest.raises(LedgerError, match="nothing was written"):
        led.measure_many(cf, [{"item": "d9", "system": "v2", "value": 0.1}, {"item": "d1", "system": "v2", "value": 0.2}])
    led.measure("d2", "v2", 0.7, cf)
    with pytest.raises(LedgerError, match="already used in another stage"):   # and the other way round
        led.measure("d2", "v1", 0.4, ex)
    assert led.verify() == []


def test_the_rule_reaches_through_the_whole_chain(led):
    ex = led.register(proto("explore", stage="explore"))["hash"]
    va = led.register(proto("validate", stage="validate", after=ex))["hash"]
    cf = led.register(proto("confirm", stage="confirm", after=va))["hash"]
    led.measure("d1", "v1", 0.5, ex)
    with pytest.raises(LedgerError, match="already used"):
        led.measure("d1", "v1", 0.5, cf)
    other = led.register(proto("another study", stage="explore"))["hash"]
    led.measure("d1", "v1", 0.5, other)                   # an unrelated chain may use the same id


def test_manifest_overlap_is_refused_at_sealing(led):
    ex = led.register(proto("explore", stage="explore"))["hash"]
    led.measure("d1", "v1", 0.5, ex)
    with pytest.raises(LedgerError, match="already used in a linked stage"):
        led.register(proto("confirm", stage="confirm", after=ex), manifest_ids=["d1", "d2", "d3"])
    res = led.overlap(["d1", "d2", "d3"], [ex])
    assert res["items"] == ["d1"] and res["remaining"] == ["d2", "d3"]
    led.register(proto("confirm", stage="confirm", after=ex), manifest_ids=res["remaining"])


def test_sealed_candidates(led):
    cf = led.register(proto("confirm", stage="confirm", systems=["v2", "v1"]))["hash"]
    led.measure("d1", "v1", 0.5, cf)
    with pytest.raises(LedgerError, match="not one of the candidates"):
        led.measure("d1", "v3", 0.5, cf)
    for bad in ([], ["a", "a"], "v1"):
        with pytest.raises(LedgerError, match="systems"):
            led.register(proto("bad", systems=bad))


def test_groups_are_kept_apart(led):
    ex = led.register(proto("explore", stage="explore", group_by="case"))["hash"]
    with pytest.raises(LedgerError, match="needs a group"):
        led.measure("d1", "v1", 0.5, ex)
    led.measure("d1", "v1", 0.5, ex, group="case-A")
    with pytest.raises(LedgerError, match="differs from a linked stage"):
        led.register(proto("confirm", stage="confirm", after=ex))            # no group_by: the groups could not be kept apart
    with pytest.raises(LedgerError, match="group per item"):
        led.register(proto("confirm", stage="confirm", after=ex, group_by="case"), manifest_ids=["d7", "d8"])
    with pytest.raises(LedgerError, match="group"):
        led.register(proto("confirm", stage="confirm", after=ex, group_by="case"), manifest_groups={"d7": "case-A", "d8": "case-B"})
    cf = led.register(proto("confirm", stage="confirm", after=ex, group_by="case"), manifest_groups={"d8": "case-B", "d9": "case-B"})["hash"]
    assert led.protocols()[cf]["body"]["manifest"]["groups"]["count"] == 1
    with pytest.raises(LedgerError, match="case 'case-A' was already used"):
        led.measure("d5", "v1", 0.5, cf, group="case-A")                     # a new item, but from a case the explore stage saw
    led.measure("d8", "v1", 0.5, cf, group="case-B")
    res = led.overlap(["d2", "d3", "d4"], [ex], groups={"d2": "case-A", "d3": "case-C", "d4": "case-A"})
    assert res["groups"] == ["case-A"] and res["remaining"] == ["d3"]
    assert led.verify() == []


def test_group_map_is_checked_by_verify(led):
    groups = {"d1": "g1", "d2": "g2"}
    h = led.register(proto("m", group_by="site"), manifest_groups=groups)["hash"]
    led.measure("d1", "v1", 0.5, h, group="g1")
    assert led.check_manifest(list(groups), groups=groups) == []
    led.measure("d2", "v1", 0.5, h, group="g9")
    probs = led.check_manifest(list(groups), groups=groups)
    assert len(probs) == 1 and "g9" in probs[0]
    assert "differs" in led.check_manifest(list(groups), groups={"d1": "g1", "d2": "g3"})[0]


def test_verify_catches_reuse_written_by_hand(led, tmp_path):
    ex = led.register(proto("explore", stage="explore"))["hash"]
    cf = led.register(proto("confirm", stage="confirm", after=ex))["hash"]
    led.measure("d1", "v1", 0.5, ex)
    es = led.entries()
    forged = Ledger._chain(es, [("measurement", {"id": "v1::d1", "item": "d1", "system": "v1", "protocol": cf, "value": 0.9})], None)
    led._write(forged)
    probs = led.verify()
    assert any("already used in another stage" in p for p in probs)


def test_cli_stages_overlap_and_report(tmp_path, capsys):
    d = str(tmp_path / ".fseal")
    main(["--dir", d, "init"])
    (tmp_path / "ex.json").write_text(json.dumps(proto("explore", stage="explore", group_by="case")))
    (tmp_path / "ex_items.tsv").write_text("d1\tA\nd2\tA\nd3\tB\n")
    main(["--dir", d, "register", str(tmp_path / "ex.json"), "--manifest", str(tmp_path / "ex_items.tsv")])
    out = capsys.readouterr().out
    assert "stage: explore, after nothing" in out and "sealed groups: 2 distinct" in out
    ex = Ledger(d).head()
    main(["--dir", d, "measure", "--item", "d1", "--system", "v1", "--value", "0.5", "--group", "A", "--protocol", ex])
    (tmp_path / "cand.tsv").write_text("d2\tA\nd4\tC\nd5\tC\n")
    with pytest.raises(SystemExit) as e:
        main(["--dir", d, "overlap", str(tmp_path / "cand.tsv"), "--after", ex, "--write-remaining", str(tmp_path / "next.tsv")])
    assert e.value.code == 1
    assert (tmp_path / "next.tsv").read_text() == "d4\tC\nd5\tC\n"
    (tmp_path / "cf.json").write_text(json.dumps(proto("confirm", stage="confirm", after=ex, group_by="case", systems=["v1", "v2"])))
    main(["--dir", d, "register", str(tmp_path / "cf.json"), "--manifest", str(tmp_path / "next.tsv")])
    assert "sealed candidates: v1, v2" in capsys.readouterr().out
    cf = Ledger(d).head()
    (tmp_path / "m.csv").write_text("item,system,value,case\nd4,v1,0.4,C\nd4,v2,0.6,C\nd5,v1,0.5,C\nd5,v2,0.7,C\n")
    main(["--dir", d, "import-csv", str(tmp_path / "m.csv"), "--protocol", cf, "--group-col", "case"])
    main(["--dir", d, "verify", "--manifest", str(tmp_path / "next.tsv")])
    page = report.build(Ledger(d), cf)
    assert "Stage" in page and "after explore (explore" in page and "Groups kept apart" in page and "Sealed candidates" in page
