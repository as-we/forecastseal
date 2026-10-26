"""Scoring and testing, standard library only.

Per-item losses are proper scoring rules (log loss, multi-class Brier). Comparisons are paired on
events both forecasters predicted. Intervals come from a seeded percentile bootstrap.
Power uses a normal approximation: treat the numbers as planning guides, not guarantees
(see the README for the small-sample caveat).
"""
from __future__ import annotations

import math
import random
from statistics import NormalDist, mean, stdev

EPS = 1e-15
_N = NormalDist()


def log_loss(probs: dict, outcome: str) -> float:
    return -math.log(max(probs[outcome], EPS))


def brier(probs: dict, outcome: str) -> float:
    return sum((p - (1.0 if k == outcome else 0.0)) ** 2 for k, p in probs.items())


LOSSES = {"log_loss": log_loss, "brier": brier}


def _loss(r: dict, metric: str) -> float:
    """Per-row value: a measured value as is, or the loss of a probability forecast."""
    return r["value"] if "value" in r else LOSSES[metric](r["probs"], r["outcome"])


def _by_forecaster(rows: list[dict], metric: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        d = out.setdefault(r["forecaster"], {})
        if r["event"] in d:
            raise ValueError(f"{r['forecaster']!r} has two entries for {r['event']!r}; use one per forecaster and event")
        d[r["event"]] = _loss(r, metric)
    return out


def loss_lists(rows: list[dict], metric: str) -> dict[str, list[float]]:
    """Per-forecaster list of per-event losses (event order)."""
    return {k: [d[e] for e in sorted(d)] for k, d in _by_forecaster(rows, metric).items()}


def score(rows: list[dict], metric: str) -> dict[str, dict]:
    res = {}
    for name, d in _by_forecaster(rows, metric).items():
        v = list(d.values())
        res[name] = {"n": len(v), "mean": mean(v), "sd": stdev(v) if len(v) > 1 else float("nan")}
    return res


def paired_diffs(rows: list[dict], metric: str, a: str, b: str) -> list[float]:
    """loss(a) - loss(b) per shared event; negative means a is better."""
    by = _by_forecaster(rows, metric)
    if a not in by or b not in by:
        raise ValueError(f"unknown forecaster; known: {sorted(by)}")
    shared = sorted(set(by[a]) & set(by[b]))
    return [by[a][e] - by[b][e] for e in shared]


def bootstrap_ci(values: list[float], level: float, n_boot: int = 2000, seed: int = 43) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)  # nosec B311 - reproducible resampling, not a security use
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int(((1 - level) / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - (1 - level) / 2) * n_boot))]
    return (lo, hi)


def compare(rows: list[dict], metric: str, a: str, b: str, alpha: float, n_comparisons: int = 1, seed: int = 43,
            n_boot: int = 2000, higher_is_better: bool = False) -> dict:
    """Difference is always a minus b. ``better`` says which one the sign favours (None if the interval includes 0)."""
    d = paired_diffs(rows, metric, a, b)
    alpha_adj = alpha / n_comparisons
    lo, hi = bootstrap_ci(d, 1 - alpha_adj, n_boot, seed)
    excl = (lo > 0 or hi < 0) if len(d) > 1 else False
    m = mean(d) if d else float("nan")
    better = None
    if excl:
        a_wins = (m > 0) if higher_is_better else (m < 0)
        better = a if a_wins else b
    return {"n": len(d), "mean_diff": m, "sd": stdev(d) if len(d) > 1 else float("nan"), "alpha_adj": alpha_adj,
            "ci": (lo, hi), "excludes_zero": excl, "better": better, "higher_is_better": higher_is_better}


def calibration(rows: list[dict], bins: int = 10) -> dict:
    """Reliability over every (event, outcome label) pair; ECE is the count-weighted mean gap."""
    if any("value" in r for r in rows):
        raise ValueError("calibration applies to probability forecasts, not measured values")
    pairs = [(p, 1.0 if k == r["outcome"] else 0.0) for r in rows for k, p in r["probs"].items()]
    out = []
    ece = 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, y) for p, y in pairs if (lo <= p < hi) or (i == bins - 1 and p == 1.0)]
        if sel:
            mp, my = mean(p for p, _ in sel), mean(y for _, y in sel)
            ece += len(sel) / len(pairs) * abs(mp - my)
            out.append({"lo": lo, "hi": hi, "n": len(sel), "mean_pred": mp, "freq": my})
    return {"bins": out, "ece": ece, "n": len(pairs)}


def power(n: int, delta: float, sd: float, alpha: float, two_sided: bool = True) -> float:
    """Chance of detecting a true mean difference `delta` with n paired items (normal approximation)."""
    if n < 1 or sd <= 0:
        return float("nan")
    se = sd / math.sqrt(n)
    crit = _N.inv_cdf(1 - alpha / (2 if two_sided else 1))
    z = abs(delta) / se
    return (1 - _N.cdf(crit - z)) + (_N.cdf(-crit - z) if two_sided else 0.0)


def required_n(delta: float, sd: float, alpha: float, target_power: float = 0.8, two_sided: bool = True) -> int:
    za = _N.inv_cdf(1 - alpha / (2 if two_sided else 1))
    zb = _N.inv_cdf(target_power)
    return math.ceil(((za + zb) * sd / abs(delta)) ** 2)


def min_detectable(n: int, sd: float, alpha: float, target_power: float = 0.8, two_sided: bool = True) -> float:
    za = _N.inv_cdf(1 - alpha / (2 if two_sided else 1))
    zb = _N.inv_cdf(target_power)
    return (za + zb) * sd / math.sqrt(n)
