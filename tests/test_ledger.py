import json
import time
import multiprocessing as mp
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
    assert (st["predictions"], st["resolved_events"], st["open_events"]) == (2, 1, 1)


def test_two_forecasters_one_event(led):
    h = sealed(led)
    led.predict("A1", h, "A", {"yes": 0.7, "no": 0.3}, event="e1")
    led.predict("B1", h, "B", {"yes": 0.4, "no": 0.6}, event="e1")
    led.resolve("e1", "yes")
    assert len(led.resolved_items(h)) == 2


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


def test_deleting_or_reordering_is_detected(led):
    h = sealed(led)
    led.predict("p1", h, "me", {"yes": 0.7, "no": 0.3})
    led.predict("p2", h, "me", {"yes": 0.6, "no": 0.4})
    lines = led.path.read_text(encoding="utf-8").splitlines()
    led.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert led.verify() != []
    led.path.write_text("\n".join([lines[0], lines[2], lines[1]]) + "\n", encoding="utf-8")
    assert led.verify() != []


def test_truncating_the_tail_needs_an_anchored_head(led):
    h = sealed(led)
    led.predict("p1", h, "me", {"yes": 0.7, "no": 0.3})
    led.resolve("p1", "yes")
    anchored = led.head()
    lines = led.path.read_text(encoding="utf-8").splitlines()
    led.path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")   # remove the outcome
    assert led.verify() == []                                            # chain alone cannot see it
    assert any("expected head" in p for p in led.verify(expected_head=anchored))


def test_prediction_after_the_outcome_is_refused_and_flagged(led):
    h = sealed(led)
    led.predict("A1", h, "A", {"yes": 0.7, "no": 0.3}, event="e1")
    led.resolve("e1", "yes")
    with pytest.raises(LedgerError):
        led.predict("B1", h, "B", {"yes": 0.99, "no": 0.01}, event="e1")
    # a hand-built entry that skips the checks is still caught by verify()
    led._append("prediction", {"id": "B1", "event": "e1", "protocol": h, "forecaster": "B", "probs": {"yes": 0.99, "no": 0.01}})
    assert any("after its event" in p for p in led.verify())


def test_protocol_must_be_valid(led):
    for bad in ({"name": "x"}, {**PROTO, "metric": "accuracy"}, {**PROTO, "alpha": 1.5}, {**PROTO, "alpha": True},
                {**PROTO, "n_target": 0}, {**PROTO, "n_target": True}, {**PROTO, "n_comparisons": 0}, [1, 2], "text"):
        with pytest.raises(LedgerError):
            led.register(bad)


def test_prediction_rules(led):
    h = sealed(led)
    with pytest.raises(LedgerError):
        led.predict("p1", "deadbeef", "me", {"yes": 0.5, "no": 0.5})
    for bad in ({"yes": 0.6, "no": 0.6}, {"yes": 1.0}, {"yes": float("nan"), "no": 0.5}, {"yes": True, "no": 0.0},
                {"yes": "0.5", "no": 0.5}, {"yes": 1.2, "no": -0.2}, [0.5, 0.5]):
        with pytest.raises(LedgerError):
            led.predict("p1", h, "me", bad)
    led.predict("p1", h, "me", {"yes": 0.5, "no": 0.5})
    with pytest.raises(LedgerError):
        led.predict("p1", h, "me", {"yes": 0.4, "no": 0.6})


def test_resolve_rules(led):
    h = sealed(led)
    led.predict("p1", h, "me", {"yes": 0.5, "no": 0.5})
    with pytest.raises(LedgerError):
        led.resolve("nope", "yes")
    with pytest.raises(LedgerError):
        led.resolve("p1", "maybe")
    led.resolve("p1", "yes")
    with pytest.raises(LedgerError):
        led.resolve("p1", "no")


def test_control_characters_are_refused(led):
    h = sealed(led)
    for bad in ("evil\x1b[31m", "tab\tname", "", "   ", "x" * 300, 5):
        with pytest.raises(LedgerError):
            led.predict(bad, h, "me", {"yes": 0.5, "no": 0.5})
    with pytest.raises(LedgerError):
        led.predict("ok", h, "bad\nname", {"yes": 0.5, "no": 0.5})


def test_non_finite_numbers_in_the_file_are_refused(led):
    sealed(led)
    with led.path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 2, "type": "prediction", "body": {"x": NaN}}\n')
    with pytest.raises(LedgerError):
        led.entries()


def test_garbage_lines_do_not_crash_verify(led):
    sealed(led)
    with led.path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 2, "type": "prediction", "body": 5, "prev": 1, "hash": 2, "ts": null}\n')
    assert led.verify() != []


def test_init_twice_is_refused(led):
    with pytest.raises(LedgerError):
        led.init()


def _worker(args):
    root, h, k = args
    l = Ledger(root)
    for i in range(10):
        l.predict(f"w{k}-{i}", h, "me", {"yes": 0.5, "no": 0.5})


def test_concurrent_writers_keep_one_chain(led):
    h = sealed(led)
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
    with ctx.Pool(4) as pool:
        pool.map(_worker, [(str(led.root), h, k) for k in range(4)])
    assert led.verify() == []
    assert led.status()["predictions"] == 40


def test_cli_roundtrip_and_interim_rules(tmp_path, capsys):
    d = str(tmp_path / ".fseal")
    pf = tmp_path / "protocol.json"
    pf.write_text(json.dumps({**PROTO, "n_target": 40}))
    main(["--dir", d, "init"])
    main(["--dir", d, "register", str(pf)])
    h = Ledger(d).head()
    for i in range(10):
        ev = f"e{i}"
        main(["--dir", d, "predict", "--id", f"A{i}", "--event", ev, "--forecaster", "A", "--probs", '{"yes":0.6,"no":0.4}'])
        main(["--dir", d, "predict", "--id", f"B{i}", "--event", ev, "--forecaster", "B", "--probs", '{"yes":0.9,"no":0.1}'])
        main(["--dir", d, "resolve", ev, "yes" if i % 5 else "no"])
    main(["--dir", d, "verify"])
    with pytest.raises(SystemExit) as ex:                   # 10 of 40: no verdict without --interim
        main(["--dir", d, "test", "A", "B"])
    assert ex.value.code == 2
    main(["--dir", d, "test", "A", "B", "--interim"])
    out = capsys.readouterr().out
    assert "INTERIM" in out and "ledger intact" in out
    assert Ledger(d).status()["analyses"] == 1              # the look was recorded
    main(["--dir", d, "score"])
    main(["--dir", d, "calibration"])
    main(["--dir", d, "power", "--sd", "0.085", "--delta", "0.004"])
    assert "events needed" in capsys.readouterr().out


def _big_writer(args):
    root, h, k = args
    l = Ledger(root)
    pad = "x" * 3000                                          # long lines are more likely to be seen half-written
    for i in range(25):
        l.predict(f"b{k}-{i}", h, "me", {"yes": 0.5, "no": 0.5}, meta={"pad": pad})


def _reader(args):
    root, n = args
    l = Ledger(root)
    for _ in range(n):
        l.entries()                                           # must never see a half-written line


def test_readers_never_see_a_half_written_line_while_others_write(led):
    h = sealed(led)
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
    with ctx.Pool(8) as pool:
        w = [pool.apply_async(_big_writer, ((str(led.root), h, k),)) for k in range(4)]
        r = [pool.apply_async(_reader, ((str(led.root), 400),)) for _ in range(4)]
        for x in w + r:
            x.get(timeout=300)
    assert led.verify() == [] and led.status()["predictions"] == 100


def _slow_partial_write(args):
    root, started, line = args
    l = Ledger(root)
    half = len(line) // 2
    with l._lock():                                           # a writer in the middle of appending
        with l.path.open("a", encoding="utf-8") as fh:
            fh.write(line[:half]); fh.flush()
            started.set()
            time.sleep(0.6)
            fh.write(line[half:] + "\n"); fh.flush()


def test_a_reader_waits_for_a_writer_that_is_halfway_through_a_line(led):
    h = sealed(led)
    good = led._chain(led.entries(), [("analysis", {"protocol": h, "kind": "interim", "what": "probe", "n_resolved": 0})], None)[0]
    line = json.dumps(good, sort_keys=True)
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
    started = ctx.Event()
    p = ctx.Process(target=_slow_partial_write, args=((str(led.root), started, line),))
    p.start()
    assert started.wait(10)
    entries = Ledger(led.root).entries()                      # must block until the line is complete, not fail
    p.join()
    assert len(entries) == 2 and led.verify() == []
