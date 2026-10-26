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
