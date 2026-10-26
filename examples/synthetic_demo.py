"""Synthetic demo: no real-world data. Two forecasters predict binary events whose true
probabilities are known. B has a small genuine edge over A. The demo builds a ledger and shows
how many events it takes to see that edge.

    python examples/synthetic_demo.py            # writes ./demo_ledger/ and prints a summary
"""
import json
import math
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forecastseal import Ledger, stats  # noqa: E402


def build(root, n_events=400, edge=0.35, seed=7):
    rng = random.Random(seed)
    led = Ledger(root)
    led.init()
    h = led.register({"name": "synthetic-demo", "metric": "log_loss", "n_target": n_events, "alpha": 0.05, "n_comparisons": 1})["hash"]
    sig = lambda x: 1 / (1 + math.exp(-x))
    for i in range(n_events):
        base = rng.gauss(0, 1.2)                      # what both forecasters can see
        hidden = rng.gauss(0, 0.5)                    # what only B partly sees
        true_p = sig(base + hidden)
        a = sig(base)
        b = sig(base + edge * hidden)
        eid = f"e{i}"
        led.predict(f"A-{eid}", h, "A", {"yes": a, "no": 1 - a}, event=eid)
        led.predict(f"B-{eid}", h, "B", {"yes": b, "no": 1 - b}, event=eid)
        led.resolve(eid, "yes" if rng.random() < true_p else "no")
    return led, h


if __name__ == "__main__":
    out = Path("demo_ledger")
    if out.exists():
        shutil.rmtree(out)
    led, h = build(out)
    rows = led.resolved_items(h)
    print(json.dumps({k: round(v["mean"], 4) for k, v in stats.score(rows, "log_loss").items()}))
    r = stats.compare(rows, "log_loss", "B", "A", 0.05)
    print("B minus A:", round(r["mean_diff"], 4), "interval", tuple(round(x, 4) for x in r["ci"]), "excludes 0:", r["excludes_zero"])
    print("verify:", led.verify() or "intact")
