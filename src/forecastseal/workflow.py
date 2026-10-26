"""Shared steps used by both ``fseal test`` and ``fseal report`` so the rules are the same everywhere."""
from __future__ import annotations

from . import stats
from .ledger import Ledger, LedgerError


def protocol_of(led: Ledger, protocol_hash: str) -> dict:
    return led.protocols()[protocol_hash]["body"]["protocol"]


def direction_text(proto: dict) -> str:
    return "higher is better" if proto.get("direction") == "higher_is_better" else "lower is better"


def compare_logged(led: Ledger, protocol_hash: str, a: str, b: str, interim: bool = False, seed: int = 43) -> dict:
    """Paired comparison under the sealed protocol.

    Before ``n_target`` events are resolved this refuses unless ``interim`` is set; an interim look is
    recorded in the ledger and flagged as not a verdict. Every call is recorded.
    """
    proto = protocol_of(led, protocol_hash)
    rows = led.items_for(protocol_hash)
    hib = proto.get("direction") == "higher_is_better"
    try:
        res = stats.compare(rows, proto["metric"], a, b, proto["alpha"], proto.get("n_comparisons", 1), seed=seed, higher_is_better=hib)
    except ValueError as e:
        raise LedgerError(str(e)) from e
    final = res["n"] >= proto["n_target"]
    if not final and not interim:
        raise LedgerError(f"only {res['n']} of the {proto['n_target']} planned items are complete for both. "
                          "Wait, or pass --interim (the look is recorded in the ledger and is not a verdict).")
    prior_final = sum(1 for e in led.entries() if e["type"] == "analysis" and e["body"]["protocol"] == protocol_hash and e["body"]["kind"] == "final")
    led.log_analysis(protocol_hash, "final" if final else "interim", f"test {a} vs {b}", res["n"])
    res.update({"a": a, "b": b, "final": final, "prior_final": prior_final, "planned": proto.get("n_comparisons", 1),
                "metric": proto["metric"], "alpha": proto["alpha"], "direction": proto.get("direction", "lower_is_better")})
    return res
