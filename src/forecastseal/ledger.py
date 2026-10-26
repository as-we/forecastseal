"""Append-only, hash-chained ledger stored as JSON lines.

Each entry commits to its predecessor's hash, so editing, deleting or reordering any
earlier entry breaks every later hash and is found by ``Ledger.verify()``.

Limits (also stated in the README): the timestamps come from the local clock. The chain
proves the ledger was not edited *after* you publish or anchor its head hash somewhere
outside your control (a Git push, a timestamp service). It does not prove when it was written.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

GENESIS = "0" * 64
LEDGER_FILE = "ledger.jsonl"
PROTOCOL_REQUIRED = ("name", "metric", "n_target", "alpha")
METRICS = ("log_loss", "brier")


class LedgerError(Exception):
    """Raised for invalid input or a broken ledger."""


def canonical(obj) -> bytes:
    """Deterministic JSON bytes used for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def entry_hash(seq: int, etype: str, ts: str, prev: str, body: dict) -> str:
    return hashlib.sha256(canonical({"seq": seq, "type": etype, "ts": ts, "prev": prev, "body": body})).hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, root: str | Path = ".fseal"):
        self.root = Path(root)
        self.path = self.root / LEDGER_FILE

    # ---------- storage ----------
    def init(self) -> None:
        if self.path.exists():
            raise LedgerError(f"{self.path} already exists")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    def entries(self) -> list[dict]:
        if not self.path.exists():
            raise LedgerError(f"no ledger at {self.path}; run `fseal init` first")
        out = []
        with self.path.open(encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        raise LedgerError(f"line {n}: not valid JSON ({e})") from e
        return out

    def head(self) -> str:
        es = self.entries()
        return es[-1]["hash"] if es else GENESIS

    def _append(self, etype: str, body: dict, now: str | None = None) -> dict:
        es = self.entries()
        seq = len(es) + 1
        prev = es[-1]["hash"] if es else GENESIS
        ts = now or _now()
        e = {"seq": seq, "type": etype, "ts": ts, "prev": prev, "body": body, "hash": entry_hash(seq, etype, ts, prev, body)}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n")
        return e

    # ---------- commands ----------
    def register(self, protocol: dict, source_bytes: bytes | None = None, now: str | None = None) -> dict:
        missing = [k for k in PROTOCOL_REQUIRED if k not in protocol]
        if missing:
            raise LedgerError(f"protocol is missing: {', '.join(missing)}")
        if protocol["metric"] not in METRICS:
            raise LedgerError(f"metric must be one of {METRICS}")
        if not (isinstance(protocol["n_target"], int) and protocol["n_target"] > 0):
            raise LedgerError("n_target must be a positive integer")
        if not (0 < protocol["alpha"] < 1):
            raise LedgerError("alpha must be between 0 and 1")
        body = {"protocol": protocol}
        if source_bytes is not None:
            body["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
        e = self._append("protocol", body, now)
        return e

    def protocols(self) -> dict[str, dict]:
        return {e["hash"]: e for e in self.entries() if e["type"] == "protocol"}

    def predict(self, pid: str, protocol_hash: str, forecaster: str, probs: dict, meta: dict | None = None, now: str | None = None) -> dict:
        if protocol_hash not in self.protocols():
            raise LedgerError("unknown protocol hash; register the protocol before predicting")
        if any(e["type"] == "prediction" and e["body"]["id"] == pid for e in self.entries()):
            raise LedgerError(f"prediction id {pid!r} already exists (the ledger is append-only)")
        if not probs or len(probs) < 2:
            raise LedgerError("probs needs at least two outcomes, e.g. {'yes': 0.7, 'no': 0.3}")
        for k, v in probs.items():
            if not (isinstance(v, (int, float)) and 0.0 <= v <= 1.0 and math.isfinite(v)):
                raise LedgerError(f"probability for {k!r} must be a number in [0, 1]")
        if abs(sum(probs.values()) - 1.0) > 1e-6:
            raise LedgerError(f"probabilities must sum to 1 (got {sum(probs.values()):.6f})")
        body = {"id": pid, "protocol": protocol_hash, "forecaster": forecaster, "probs": probs}
        if meta:
            body["meta"] = meta
        return self._append("prediction", body, now)

    def resolve(self, pid: str, outcome: str, now: str | None = None) -> dict:
        preds = {e["body"]["id"]: e for e in self.entries() if e["type"] == "prediction"}
        if pid not in preds:
            raise LedgerError(f"no prediction with id {pid!r}")
        if outcome not in preds[pid]["body"]["probs"]:
            raise LedgerError(f"outcome {outcome!r} is not one of {list(preds[pid]['body']['probs'])}")
        if any(e["type"] == "outcome" and e["body"]["id"] == pid for e in self.entries()):
            raise LedgerError(f"{pid!r} is already resolved")
        return self._append("outcome", {"id": pid, "outcome": outcome}, now)

    # ---------- verification ----------
    def verify(self) -> list[str]:
        """Return a list of problems (empty list = the ledger is intact)."""
        problems: list[str] = []
        prev = GENESIS
        protos: set[str] = set()
        pred_ids: dict[str, str] = {}
        resolved: set[str] = set()
        for i, e in enumerate(self.entries(), 1):
            if e.get("seq") != i:
                problems.append(f"entry {i}: seq is {e.get('seq')}, expected {i}")
            if e.get("prev") != prev:
                problems.append(f"entry {i}: prev hash does not match the previous entry")
            want = entry_hash(e.get("seq"), e.get("type"), e.get("ts"), e.get("prev"), e.get("body"))
            if e.get("hash") != want:
                problems.append(f"entry {i}: content does not match its hash (edited?)")
            prev = e.get("hash", "")
            t, b = e.get("type"), e.get("body", {})
            if t == "protocol":
                protos.add(e.get("hash"))
            elif t == "prediction":
                if b.get("protocol") not in protos:
                    problems.append(f"entry {i}: prediction refers to an unregistered protocol")
                if b.get("id") in pred_ids:
                    problems.append(f"entry {i}: duplicate prediction id {b.get('id')!r}")
                pred_ids[b.get("id")] = e.get("ts")
            elif t == "outcome":
                if b.get("id") not in pred_ids:
                    problems.append(f"entry {i}: outcome for an unknown prediction")
                elif b.get("id") in resolved:
                    problems.append(f"entry {i}: prediction {b.get('id')!r} resolved twice")
                resolved.add(b.get("id"))
            else:
                problems.append(f"entry {i}: unknown type {t!r}")
        return problems

    def status(self) -> dict:
        es = self.entries()
        ps = [e for e in es if e["type"] == "prediction"]
        os_ = {e["body"]["id"] for e in es if e["type"] == "outcome"}
        return {"entries": len(es), "protocols": len(self.protocols()), "predictions": len(ps),
                "resolved": len(os_), "open": len(ps) - len(os_), "head": self.head()}
