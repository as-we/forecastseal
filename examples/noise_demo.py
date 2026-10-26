"""How often does pure noise look like a discovery?

Nothing real is going on in this data: two versions of a system are the same, and every
"metric" is random. An analyst (or an AI assistant) who tries 20 ways of measuring and
reports the best one finds something "significant" far more often than 5% of the time.

    python examples/noise_demo.py

Part 1 simulates many studies. Part 2 shows one study in a forecastseal ledger, where only
one metric was declared as the conclusion before the data came in.
"""
import math
import random
import shutil
import sys
from pathlib import Path
from statistics import NormalDist, mean, stdev

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forecastseal import Ledger, workflow  # noqa: E402

N_ITEMS, N_SIM_ITEMS, N_METRICS, N_STUDIES, ALPHA = 40, 200, 20, 2000, 0.05   # 200 items in the simulation keeps the normal approximation honest
N = NormalDist()


def p_value(diffs):
    se = stdev(diffs) / math.sqrt(len(diffs))
    return 2 * (1 - N.cdf(abs(mean(diffs) / se)))


def simulate(seed=1):
    rng = random.Random(seed)
    first_only = best_of_all = best_adjusted = 0
    for _ in range(N_STUDIES):
        ps = [p_value([rng.gauss(0, 1) for _ in range(N_SIM_ITEMS)]) for _ in range(N_METRICS)]
        first_only += ps[0] < ALPHA                      # one metric, named in advance
        best_of_all += min(ps) < ALPHA                   # try all 20, report the best
        best_adjusted += min(ps) < ALPHA / N_METRICS     # try all 20, but pay for having tried
    return first_only / N_STUDIES, best_of_all / N_STUDIES, best_adjusted / N_STUDIES


def one_study(root="noise_ledger"):
    """A single noise-only study in a ledger: 1 primary metric declared up front, 19 exploratory."""
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    led = Ledger(root)
    led.init()
    metrics = [{"name": f"metric-{i + 1:02d}", "direction": "higher_is_better", "primary": i == 0} for i in range(N_METRICS)]
    h = led.register({"name": "noise-only", "kind": "measure", "n_target": N_ITEMS, "alpha": ALPHA, "metrics": metrics})["hash"]
    for seed in range(1, 200):                           # find a noise-only study where some exploratory metric 'works'
        rng = random.Random(seed)
        data = {m["name"]: [(rng.gauss(0, 1), rng.gauss(0, 1)) for _ in range(N_ITEMS)] for m in metrics}
        ps = {k: p_value([a - b for a, b in v]) for k, v in data.items()}
        if ps["metric-01"] > 0.2 and min(ps.values()) < 0.01:
            break
    rows = [{"item": f"item-{i:02d}", "system": s, "metric": k, "value": pair[j]}
            for k, v in data.items() for i, pair in enumerate(v) for j, s in enumerate(("v2", "v1"))]
    led.measure_many(h, rows)
    best = min(ps, key=ps.get)
    print(f"\nOne noise-only study, in a ledger. Unadjusted best metric: {best} (p = {ps[best]:.4f}).")
    for name in ("metric-01", best):
        r = workflow.compare_logged(led, h, "v2", "v1", metric=name)
        role = "primary (declared before the data)" if r["primary"] else "exploratory (found after looking)"
        print(f"  {name}: {role}; interval [{r['ci'][0]:+.3f}, {r['ci'][1]:+.3f}] -> "
              + ("excludes 0" if r["excludes_zero"] else "includes 0") + (" but labelled exploratory: not a conclusion" if (not r["primary"] and r["excludes_zero"]) else ""))
    print("  Every look is in the ledger:", led.status()["analyses"], "analyses logged; verify:", led.verify() or "intact")


if __name__ == "__main__":
    one, best, adj = simulate()
    print(f"{N_STUDIES} studies, no real effect anywhere, {N_SIM_ITEMS} items, {N_METRICS} metrics each:")
    print(f"  one metric named in advance ........... 'significant' in {100 * one:4.1f}% of studies  (as designed: 5%)")
    print(f"  best of {N_METRICS}, reported as if it were the only one: {100 * best:4.1f}% of studies  (1 - 0.95^{N_METRICS} = {100 * (1 - 0.95 ** N_METRICS):.1f}%)")
    print(f"  best of {N_METRICS}, but paying for the {N_METRICS} tries: {100 * adj:4.1f}% of studies")
    one_study()
