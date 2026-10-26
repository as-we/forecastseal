import json
import pytest
from forecastseal import Ledger, LedgerError
from forecastseal.cli import main

PROTO = {"name": "demo", "metric": "log_loss", "n_target": 100, "alpha": 0.05}


@pytest.fixture
def led(tmp_path):
    l = Ledger(tmp_path / ".fseal")
    l.init()
    return l


def sealed(led):
    return led.register(PROTO)["hash"]


def test_chain_is_intact_after_normal_use(led):
    h = sealed(led)
    led.predict("p1", h, "me", {"yes": 0.7, "no": 0.3})
    led.predict("p2", h, "me", {"yes": 0.2, "no": 0.8})
    led.resolve("p1", "yes")
    assert led.verify() == []
    st = led.status()
    assert (st["predictions"], st["resolved"], st["open"]) == (2, 1, 1)


def test_editing_a_probability_is_detected(led):
    h = sealed(led)
    led.predict("p1", h, "me", {"yes": 0.7, "no": 0.3})
    led.resolve("p1", "no")
    lines = led.path.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1])
    e["body"]["probs"] = {"yes": 0.95, "no": 0.05}          # quietly improve the forecast after the fact
    lines[1] = json.dumps(e, sort_keys=True)
    led.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    problems = led.verify()
    assert problems and any("edited" in p for p in problems)


def test_deleting_an_entry_is_detected(led):
    h = sealed(led)
    led.predict("p1", h, "me", {"yes": 0.7, "no": 0.3})
    led.predict("p2", h, "me", {"yes": 0.6, "no": 0.4})
    lines = led.path.read_text(encoding="utf-8").splitlines()
    led.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert led.verify() != []


def test_reordering_is_detected(led):
    h = sealed(led)
    led.predict("p1", h, "me", {"yes": 0.7, "no": 0.3})
    led.predict("p2", h, "me", {"yes": 0.6, "no": 0.4})
    lines = led.path.read_text(encoding="utf-8").splitlines()
    led.path.write_text("\n".join([lines[0], lines[2], lines[1]]) + "\n", encoding="utf-8")
    assert led.verify() != []


def test_head_changes_with_every_entry(led):
    h0 = led.head()
    h = sealed(led)
    assert led.head() != h0 and led.head() == h


def test_protocol_must_be_valid(led):
    with pytest.raises(LedgerError):
        led.register({"name": "x"})
    with pytest.raises(LedgerError):
        led.register({**PROTO, "metric": "accuracy"})
    with pytest.raises(LedgerError):
        led.register({**PROTO, "alpha": 1.5})
    with pytest.raises(LedgerError):
        led.register({**PROTO, "n_target": 0})


def test_prediction_rules(led):
    h = sealed(led)
    with pytest.raises(LedgerError):
        led.predict("p1", "deadbeef", "me", {"yes": 0.5, "no": 0.5})   # unknown protocol
    with pytest.raises(LedgerError):
        led.predict("p1", h, "me", {"yes": 0.6, "no": 0.6})            # does not sum to 1
    with pytest.raises(LedgerError):
        led.predict("p1", h, "me", {"yes": 1.0})                       # one outcome only
    led.predict("p1", h, "me", {"yes": 0.5, "no": 0.5})
    with pytest.raises(LedgerError):
        led.predict("p1", h, "me", {"yes": 0.4, "no": 0.6})            # duplicate id: no overwriting


def test_resolve_rules(led):
    h = sealed(led)
    led.predict("p1", h, "me", {"yes": 0.5, "no": 0.5})
    with pytest.raises(LedgerError):
        led.resolve("nope", "yes")
    with pytest.raises(LedgerError):
        led.resolve("p1", "maybe")
    led.resolve("p1", "yes")
    with pytest.raises(LedgerError):
        led.resolve("p1", "no")                                         # cannot change an outcome


def test_init_twice_is_refused(led):
    with pytest.raises(LedgerError):
        led.init()


def test_cli_roundtrip(tmp_path, capsys):
    d = str(tmp_path / ".fseal")
    pf = tmp_path / "protocol.json"
    pf.write_text(json.dumps(PROTO))
    main(["--dir", d, "init"])
    main(["--dir", d, "register", str(pf)])
    h = Ledger(d).head()
    main(["--dir", d, "predict", "--id", "a", "--protocol", h, "--probs", '{"yes":0.9,"no":0.1}'])
    main(["--dir", d, "resolve", "a", "yes"])
    main(["--dir", d, "verify"])
    assert "ledger intact" in capsys.readouterr().out
    with pytest.raises(SystemExit) as ex:
        main(["--dir", d, "resolve", "a", "no"])
    assert ex.value.code == 2
