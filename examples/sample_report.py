"""Build the sample report shown in the README (synthetic data).

A study of two prompt versions on 40 items, with one primary metric and one exploratory metric.
The analyst takes three early looks (interim, logged, no verdict) and a final analysis at the planned size.

    python examples/sample_report.py            # writes docs/sample-report.html
"""
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forecastseal import Ledger, report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def build(workdir="sample_ledger", out=ROOT / "docs" / "sample-report.html"):
    workdir = Path(workdir)
    if workdir.exists():
        shutil.rmtree(workdir)
    led = Ledger(workdir)
    led.init()
    h = led.register({"name": "prompt-versions (sample)", "kind": "measure", "n_target": 40, "alpha": 0.05, "n_comparisons": 1,
                      "metrics": [{"name": "errors", "direction": "lower_is_better", "primary": True},
                                  {"name": "style", "direction": "higher_is_better", "primary": False}]})["hash"]
    rng = random.Random(7)
    page = ""
    for batch in range(4):                                   # 10 items at a time
        rows = []
        for i in range(batch * 10, batch * 10 + 10):
            base = rng.gauss(3.0, 0.8)
            for system, effect in (("v1", 0.0), ("v2", -0.45)):
                rows.append({"item": f"item-{i:02d}", "system": system, "metric": "errors", "value": base + effect + rng.gauss(0, 0.5)})
                rows.append({"item": f"item-{i:02d}", "system": system, "metric": "style", "value": 0.6 + rng.gauss(0, 0.08)})
        led.measure_many(h, rows)
        if batch < 3:                                        # an early look: logged, marked x on the timeline, no verdict
            report.build(led, h, compare=[("v2", "v1")], interim=True)
    led.close(h, "finished as planned")
    page = report.build(led, h, compare=[("v2", "v1")], now="2026-01-15T09:00:00+00:00")     # the final analysis at the planned size
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    shutil.rmtree(workdir)
    return out


if __name__ == "__main__":
    print("wrote", build())
