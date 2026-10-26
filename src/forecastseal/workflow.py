"""Shared steps used by ``fseal test`` and ``fseal report`` so the rules are the same everywhere."""
from __future__ import annotations

from . import stats
from .ledger import Ledger, LedgerError, protocol_metrics


def protocol_of(led: Ledger, protocol_hash: str) -> dict:
    return led.protocols()[protocol_hash]["body"]["protocol"]


def direction_text(direction: str) -> str:
    return "higher is better" if direction == "higher_is_better" else "lower is better"


def metrics_of(led: Ledger, protocol_hash: str) -> list[dict]:
    return protocol_metrics(protocol_of(led, protocol_hash))


def pick_metric(led: Ledger, protocol_hash: str, metric: str | None) -> dict:
    ms = metrics_of(led, protocol_hash)
    if metric is None:
        if len(ms) != 1:
            raise LedgerError(f"this protocol has several metrics {[m['name'] for m in ms]}; name one with --metric")
        return ms[0]
    for m in ms:
        if m["name"] == metric:
            return m
    raise LedgerError(f"unknown metric {metric!r}; this protocol defines {[m['name'] for m in ms]}")


def family_size(proto: dict, metric: dict) -> int:
    """Confirmatory (primary) metrics share the error budget: alpha / (primary metrics x planned comparisons).
    Exploratory metrics get no adjustment and are labelled as such."""
    if not metric["primary"]:
        return 1
    n_primary = sum(1 for m in protocol_metrics(proto) if m["primary"])
    return n_primary * proto.get("n_comparisons", 1)


def compare_logged(led: Ledger, protocol_hash: str, a: str, b: str, interim: bool = False, seed: int = 43, metric: str | None = None) -> dict:
    """Paired comparison of one metric under the sealed protocol.

    Before ``n_target`` items are complete this refuses unless ``interim`` is set; an interim look is
    recorded in the ledger and flagged as not a verdict. Every call is recorded.
    """
    proto = protocol_of(led, protocol_hash)
    m = pick_metric(led, protocol_hash, metric)
    multi = len(protocol_metrics(proto)) > 1
    rows = led.items_for(protocol_hash, m["name"])
    hib = m["direction"] == "higher_is_better"
    fam = family_size(proto, m)
    try:
        res = stats.compare(rows, m["name"], a, b, proto["alpha"], fam, seed=seed, higher_is_better=hib)
    except ValueError as e:
        raise LedgerError(str(e)) from e
    final = res["n"] >= proto["n_target"]
    if not final and not interim:
        raise LedgerError(f"only {res['n']} of the {proto['n_target']} planned items are complete for both ({m['name']}). "
                          "Wait, or pass --interim (the look is recorded in the ledger and is not a verdict).")
    prior_final = sum(1 for e in led.entries() if e["type"] == "analysis" and e["body"]["protocol"] == protocol_hash
                      and e["body"]["kind"] == "final" and e["body"].get("metric", m["name"]) == m["name"])
    led.log_analysis(protocol_hash, "final" if final else "interim", f"test {a} vs {b}", res["n"], metric=m["name"] if multi else None)
    res.update({"a": a, "b": b, "final": final, "prior_final": prior_final, "planned": proto.get("n_comparisons", 1), "metric": m["name"],
                "primary": m["primary"], "family": fam, "alpha": proto["alpha"], "direction": m["direction"], "multi": multi})
    return res
