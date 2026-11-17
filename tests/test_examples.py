import importlib.util
from pathlib import Path

EX = Path(__file__).resolve().parent.parent / "examples"


def load(name):
    spec = importlib.util.spec_from_file_location(name, EX / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_noise_demo_shows_the_inflation_and_the_labels(tmp_path, capsys):
    m = load("noise_demo")
    m.N_STUDIES = 400
    one, best, adj = m.simulate(seed=3)
    assert 0.02 < one < 0.09 and best > 0.5 and adj < 0.09           # 5% / about 64% / back near 5%
    m.one_study(tmp_path / "noise_ledger")
    out = capsys.readouterr().out
    assert "primary (declared before the data)" in out and "exploratory (found after looking)" in out and "intact" in out


def test_stages_demo_keeps_explored_generators_out_of_the_confirm_stage(tmp_path, capsys):
    m = load("stages_demo")
    led, ex, cf = m.main(root=tmp_path / "ledger", out=tmp_path / "r.html")
    out = capsys.readouterr().out
    assert "2 generator(s) already explored" in out and "generator 'gen-05' was already used" in out and "ledger: intact" in out
    seen = {e["body"]["group"] for e in led.entries() if e["type"] == "measurement" and e["body"]["protocol"] == ex}
    used = {e["body"]["group"] for e in led.entries() if e["type"] == "measurement" and e["body"]["protocol"] == cf}
    assert seen and used and not (seen & used)
    page = (tmp_path / "r.html").read_text()
    assert "Sealed candidates" in page and "By condition (descriptive)" in page


def test_peeking_demo_shows_inflated_false_alarms_and_exaggerated_estimates():
    m = load("peeking_demo")
    m.STUDIES = 600
    f0, p0, _ = m.run(0.0, seed=2)
    f1, p1, est = m.run(0.2, seed=2)
    assert p0 > f0 + 0.08                                   # peeking inflates false alarms well above the single look
    assert est > 0.3                                         # stopped-early estimates exceed the true 0.2
