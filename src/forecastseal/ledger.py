"""Append-only, hash-chained ledger stored as JSON lines.

Each entry commits to its predecessor's hash, so editing, deleting or reordering any
earlier entry breaks every later hash and is found by ``Ledger.verify()``.

Limits (also stated in the README): the timestamps come from the local clock. The chain
proves the ledger was not edited *after* you publish or anchor its head hash somewhere
outside your control (a Git push, a timestamp service). Deleting the *last* entries is only
detectable if you saved an earlier head hash: ``verify(expected_head=...)``.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import math
import functools
import os
import threading
import time
import unicodedata
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

GENESIS = "0" * 64
LEDGER_FILE = "ledger.jsonl"
LOCK_FILE = ".lock"
PROTOCOL_REQUIRED = ("name", "n_target", "alpha")
METRICS = ("log_loss", "brier")
KINDS = ("forecast", "measure")
DIRECTIONS = ("lower_is_better", "higher_is_better")
CLOSURE_KINDS = ("completed", "stopped_early", "abandoned")
MAX_TEXT = 256
MAX_META_BYTES = 10_000
MAX_LINE_BYTES = 1_000_000


class LedgerError(Exception):
    """Raised for invalid input or a broken ledger."""


def _reject_constant(name):  # NaN / Infinity are not valid JSON; refuse them everywhere
    raise ValueError(f"non-finite number {name} is not allowed")


def loads(s: str):
    return json.loads(s, parse_constant=_reject_constant)


def canonical(obj) -> bytes:
    """Deterministic JSON bytes used for hashing (NaN/Infinity are refused)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def entry_hash(seq: int, etype: str, ts: str, prev: str, body: dict) -> str:
    return hashlib.sha256(canonical({"seq": seq, "type": etype, "ts": ts, "prev": prev, "body": body})).hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def clean_text(value, what: str) -> str:
    """Names and ids go to terminals and reports: no control characters, bounded length."""
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"{what} must be a non-empty string")
    if len(value) > MAX_TEXT:
        raise LedgerError(f"{what} is longer than {MAX_TEXT} characters")
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise LedgerError(f"{what} contains control characters")
    return value


def protocol_metrics(protocol: dict) -> list[dict]:
    """The metrics a protocol defines, as [{"name", "direction", "primary"}]. A single-metric protocol has one primary metric."""
    if protocol.get("kind", "forecast") == "forecast":
        return [{"name": protocol["metric"], "direction": "lower_is_better", "primary": True, "margin": protocol.get("margin")}]
    if "metrics" in protocol:
        return [{"name": m["name"], "direction": m["direction"], "primary": bool(m.get("primary", False)), "margin": m.get("margin")} for m in protocol["metrics"]]
    return [{"name": protocol["metric"], "direction": protocol["direction"], "primary": True, "margin": protocol.get("margin")}]


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _atomic(fn):
    """Run a whole read-check-append operation under the ledger lock."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock():
            return fn(self, *args, **kwargs)
    return wrapper


class Ledger:
    def __init__(self, root: str | Path = ".fseal"):
        self.root = Path(root)
        self.path = self.root / LEDGER_FILE
        self._depth = 0
        self._tlock = threading.RLock()

    # ---------- storage ----------
    @contextlib.contextmanager
    def _lock(self):
        """Exclusive lock for reading and writing the ledger, re-entrant within one Ledger object.

        Readers take it too: without that, a reader can see a half-written last line while another
        process is appending. Every operation that reads, checks and then appends holds it for the
        whole sequence (see ``_atomic``), so two writers cannot both pass the same check.
        """
        with self._tlock:
            if self._depth > 0:
                self._depth += 1
                try:
                    yield
                finally:
                    self._depth -= 1
                return
            self.root.mkdir(parents=True, exist_ok=True)
            lock_path = self.root / LOCK_FILE
            fd = None
            try:
                if fcntl is not None:
                    fh = open(lock_path, "a")
                    fcntl.flock(fh, fcntl.LOCK_EX)
                    fd = fh
                else:  # pragma: no cover - portable fallback
                    for _ in range(400):
                        try:
                            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                            break
                        except FileExistsError:
                            time.sleep(0.05)
                    else:
                        raise LedgerError("could not obtain the ledger lock")
            except OSError:
                fd = None                                   # read-only location: reading still works, writing will fail on its own
            self._depth = 1
            try:
                yield
            finally:
                self._depth = 0
                if fd is not None:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        fd.close()
                    else:  # pragma: no cover
                        os.close(fd)
                        os.unlink(lock_path)

    def init(self) -> None:
        if self.path.exists():
            raise LedgerError(f"{self.path} already exists")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    def entries(self) -> list[dict]:
        if not self.path.exists():
            raise LedgerError(f"no ledger at {self.path}; run `fseal init` first")
        out = []
        with self._lock(), self.path.open("rb") as fh:
            for n, raw in enumerate(fh, 1):
                if len(raw) > MAX_LINE_BYTES:
                    raise LedgerError(f"line {n}: longer than {MAX_LINE_BYTES} bytes")
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    e = loads(line)
                except ValueError as ex:
                    raise LedgerError(f"line {n}: not valid JSON ({ex})") from ex
                if not isinstance(e, dict):
                    raise LedgerError(f"line {n}: entry is not an object")
                out.append(e)
        return out

    def head(self) -> str:
        es = self.entries()
        return es[-1]["hash"] if es else GENESIS

    @staticmethod
    def _chain(es: list[dict], items: list[tuple[str, dict]], now: str | None) -> list[dict]:
        """Build new entries that continue the chain after ``es``."""
        out = []
        prev = es[-1]["hash"] if es else GENESIS
        seq = len(es)
        for etype, body in items:
            seq += 1
            ts = now or _now()
            e = {"seq": seq, "type": etype, "ts": ts, "prev": prev, "body": body, "hash": entry_hash(seq, etype, ts, prev, body)}
            out.append(e)
            prev = e["hash"]
        return out

    def _write(self, new: list[dict]) -> None:
        lines = "".join(json.dumps(e, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n" for e in new)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(lines)
            fh.flush()
            os.fsync(fh.fileno())

    def _append(self, etype: str, body: dict, now: str | None = None) -> dict:
        with self._lock():
            new = self._chain(self.entries(), [(etype, body)], now)
            self._write(new)
        return new[0]

    # ---------- commands ----------
    @staticmethod
    def manifest_of(ids: list[str]) -> dict:
        """Hash of a set of item ids (sorted, one per line). The same set always gives the same hash."""
        if not isinstance(ids, (list, tuple)) or not ids:
            raise LedgerError("a manifest needs at least one item id")
        cleaned = [clean_text(i, "manifest item id") for i in ids]
        if len(set(cleaned)) != len(cleaned):
            raise LedgerError("manifest has duplicate item ids")
        digest = hashlib.sha256("\n".join(sorted(cleaned)).encode("utf-8")).hexdigest()
        return {"sha256": digest, "count": len(cleaned)}

    @_atomic
    def register(self, protocol: dict, source_bytes: bytes | None = None, now: str | None = None,
                 manifest_ids: list[str] | None = None) -> dict:
        if not isinstance(protocol, dict):
            raise LedgerError("protocol must be a JSON object")
        missing = [k for k in PROTOCOL_REQUIRED if k not in protocol]
        if missing:
            raise LedgerError(f"protocol is missing: {', '.join(missing)}")
        clean_text(protocol["name"], "protocol name")
        kind = protocol.get("kind", "forecast")
        if kind not in KINDS:
            raise LedgerError(f"kind must be one of {KINDS}")
        if kind == "forecast":
            if protocol.get("metric") not in METRICS:
                raise LedgerError(f"metric must be one of {METRICS}")
        elif "metrics" in protocol:  # several metrics under one sealed protocol
            ms = protocol["metrics"]
            if not isinstance(ms, list) or not ms or not all(isinstance(m, dict) for m in ms):
                raise LedgerError("metrics must be a non-empty list of objects")
            names = []
            for m in ms:
                names.append(clean_text(m.get("name"), "metric name"))
                if m.get("direction") not in DIRECTIONS:
                    raise LedgerError(f"metric {m.get('name')!r} needs direction: one of {DIRECTIONS}")
                if "primary" in m and not isinstance(m["primary"], bool):
                    raise LedgerError("primary must be true or false")
                if "margin" in m and not (_is_number(m["margin"]) and m["margin"] > 0):
                    raise LedgerError("margin must be a number greater than 0")
            if len(set(names)) != len(names):
                raise LedgerError("metric names must be unique")
            if not any(m.get("primary") for m in ms):
                raise LedgerError("at least one metric must be primary (the confirmatory comparison); the others are exploratory")
        else:  # a single metric: a free-text label and an explicit direction
            clean_text(protocol.get("metric"), "metric")
            if protocol.get("direction") not in DIRECTIONS:
                raise LedgerError(f"a measure protocol needs direction: one of {DIRECTIONS}")
        if "margin" in protocol and not (_is_number(protocol["margin"]) and protocol["margin"] > 0):
            raise LedgerError("margin must be a number greater than 0")
        n = protocol["n_target"]
        if not (isinstance(n, int) and not isinstance(n, bool) and n > 0):
            raise LedgerError("n_target must be a positive integer")
        if not (_is_number(protocol["alpha"]) and 0 < protocol["alpha"] < 1):
            raise LedgerError("alpha must be a number between 0 and 1")
        k = protocol.get("n_comparisons", 1)
        if not (isinstance(k, int) and not isinstance(k, bool) and k >= 1):
            raise LedgerError("n_comparisons must be a positive integer")
        if len(canonical(protocol)) > MAX_META_BYTES:
            raise LedgerError("protocol is too large")
        body = {"protocol": protocol}
        if source_bytes is not None:
            body["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
        if manifest_ids is not None:
            body["manifest"] = self.manifest_of(manifest_ids)
            if protocol["n_target"] > body["manifest"]["count"]:
                raise LedgerError(f"n_target ({protocol['n_target']}) is larger than the manifest ({body['manifest']['count']} items)")
        return self._append("protocol", body, now)

    def protocols(self) -> dict[str, dict]:
        return {e["hash"]: e for e in self.entries() if e["type"] == "protocol"}

    @_atomic
    def predict(self, pid: str, protocol_hash: str, forecaster: str, probs: dict, event: str | None = None,
                meta: dict | None = None, now: str | None = None) -> dict:
        pid = clean_text(pid, "prediction id")
        forecaster = clean_text(forecaster, "forecaster")
        event = clean_text(event if event is not None else pid, "event")
        protos = self.protocols()
        if protocol_hash not in protos:
            raise LedgerError("unknown protocol hash; register the protocol before predicting")
        if protos[protocol_hash]["body"]["protocol"].get("kind", "forecast") != "forecast":
            raise LedgerError("this protocol is a measure protocol; use measure(), not predict()")
        self._refuse_if_closed(protocol_hash)
        if not isinstance(probs, dict) or len(probs) < 2:
            raise LedgerError("probs needs at least two outcomes, e.g. {'yes': 0.7, 'no': 0.3}")
        for k, v in probs.items():
            clean_text(k, "outcome label")
            if not (_is_number(v) and 0.0 <= v <= 1.0):
                raise LedgerError(f"probability for {k!r} must be a number in [0, 1]")
        if abs(sum(probs.values()) - 1.0) > 1e-6:
            raise LedgerError(f"probabilities must sum to 1 (got {sum(probs.values()):.6f})")
        es = self.entries()
        if any(e["type"] == "prediction" and e["body"]["id"] == pid for e in es):
            raise LedgerError(f"prediction id {pid!r} already exists (the ledger is append-only)")
        if any(e["type"] == "outcome" and e["body"]["event"] == event for e in es):
            raise LedgerError(f"event {event!r} is already resolved; no new predictions for it")
        body = {"id": pid, "event": event, "protocol": protocol_hash, "forecaster": forecaster, "probs": probs}
        if meta is not None:
            if not isinstance(meta, dict) or len(canonical(meta)) > MAX_META_BYTES:
                raise LedgerError("meta must be a small JSON object")
            body["meta"] = meta
        return self._append("prediction", body, now)

    def _metric_name(self, protocol: dict, metric: str | None) -> str:
        names = [m["name"] for m in protocol_metrics(protocol)]
        if metric is None:
            if len(names) != 1:
                raise LedgerError(f"this protocol has several metrics {names}; name one with metric=")
            return names[0]
        if metric not in names:
            raise LedgerError(f"unknown metric {metric!r}; this protocol defines {names}")
        return metric

    @_atomic
    def measure(self, item: str, system: str, value: float, protocol_hash: str, metric: str | None = None,
                meta: dict | None = None, now: str | None = None) -> dict:
        """Record one score of one system on one item (for protocols of kind 'measure')."""
        item = clean_text(item, "item")
        system = clean_text(system, "system")
        protos = self.protocols()
        if protocol_hash not in protos:
            raise LedgerError("unknown protocol hash; register the protocol before measuring")
        proto = protos[protocol_hash]["body"]["protocol"]
        if proto.get("kind", "forecast") != "measure":
            raise LedgerError("this protocol is a forecast protocol; use predict(), not measure()")
        self._refuse_if_closed(protocol_hash)
        metric = self._metric_name(proto, metric)
        if not _is_number(value):
            raise LedgerError("value must be a finite number")
        if any(e["type"] == "measurement" and e["body"]["protocol"] == protocol_hash and e["body"]["item"] == item
               and e["body"]["system"] == system and e["body"].get("metric", metric) == metric for e in self.entries()):
            raise LedgerError(f"{system!r} already has a value for item {item!r} on {metric!r} (append-only; give a re-run a new system name)")
        multi = len(protocol_metrics(proto)) > 1
        body = {"id": f"{system}::{item}" + (f"::{metric}" if multi else ""), "item": item, "system": system, "protocol": protocol_hash, "value": value}
        if multi:
            body["metric"] = metric
        if meta is not None:
            if not isinstance(meta, dict) or len(canonical(meta)) > MAX_META_BYTES:
                raise LedgerError("meta must be a small JSON object")
            body["meta"] = meta
        return self._append("measurement", body, now)

    @_atomic
    def measure_many(self, protocol_hash: str, rows: list[dict], skip_existing: bool = False, now: str | None = None) -> dict:
        """Record many measurements in one step: all rows are checked first and nothing is written if any is invalid.

        Each row: {"item", "system", "value", optional "metric", optional "meta"}. Returns {"added", "skipped"}.
        """
        with self._lock():
            es = self.entries()
            protos = {e["hash"]: e for e in es if e["type"] == "protocol"}
            if protocol_hash not in protos:
                raise LedgerError("unknown protocol hash; register the protocol before measuring")
            proto = protos[protocol_hash]["body"]["protocol"]
            if proto.get("kind", "forecast") != "measure":
                raise LedgerError("this protocol is a forecast protocol; use predict(), not measure()")
            if any(e["type"] == "closure" and e["body"]["protocol"] == protocol_hash for e in es):
                raise LedgerError("this study is closed; start a new protocol (and say so) instead of adding to a closed one")
            multi = len(protocol_metrics(proto)) > 1
            seen = {(e["body"]["item"], e["body"]["system"], e["body"].get("metric")) for e in es
                    if e["type"] == "measurement" and e["body"]["protocol"] == protocol_hash}
            items, errors, skipped = [], [], 0
            for n, r in enumerate(rows, 1):
                try:
                    if not isinstance(r, dict):
                        raise LedgerError("row is not an object")
                    item, system = clean_text(r.get("item"), "item"), clean_text(r.get("system"), "system")
                    metric = self._metric_name(proto, r.get("metric"))
                    if not _is_number(r.get("value")):
                        raise LedgerError("value must be a finite number")
                    key = (item, system, metric if multi else None)
                    if key in seen:
                        if skip_existing:
                            skipped += 1
                            continue
                        raise LedgerError(f"{system!r} already has a value for item {item!r} on {metric!r}")
                    seen.add(key)
                    body = {"id": f"{system}::{item}" + (f"::{metric}" if multi else ""), "item": item, "system": system,
                            "protocol": protocol_hash, "value": r["value"]}
                    if multi:
                        body["metric"] = metric
                    meta = r.get("meta")
                    if meta is not None:
                        if not isinstance(meta, dict) or len(canonical(meta)) > MAX_META_BYTES:
                            raise LedgerError("meta must be a small JSON object")
                        body["meta"] = meta
                    items.append(("measurement", body))
                except LedgerError as ex:
                    errors.append(f"row {n}: {ex}")
            if errors:
                more = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
                raise LedgerError("nothing was written. " + "; ".join(errors[:5]) + more)
            if items:
                self._write(self._chain(es, items, now))
        return {"added": len(items), "skipped": skipped}

    def measured_items(self, protocol_hash: str, metric: str | None = None) -> list[dict]:
        """One row per measurement of one metric, shaped like resolved_items() rows."""
        proto = self.protocols()[protocol_hash]["body"]["protocol"]
        metric = self._metric_name(proto, metric)
        multi = len(protocol_metrics(proto)) > 1
        return [{"id": e["body"]["id"], "event": e["body"]["item"], "forecaster": e["body"]["system"], "value": e["body"]["value"]}
                for e in self.entries() if e["type"] == "measurement" and e["body"]["protocol"] == protocol_hash
                and (e["body"].get("metric") == metric if multi else True)]

    def items_for(self, protocol_hash: str, metric: str | None = None) -> list[dict]:
        """Rows used for scoring, whichever kind the protocol is."""
        kind = self.protocols()[protocol_hash]["body"]["protocol"].get("kind", "forecast")
        return self.measured_items(protocol_hash, metric) if kind == "measure" else self.resolved_items(protocol_hash)

    @_atomic
    def resolve(self, event: str, outcome: str, now: str | None = None) -> dict:
        event = clean_text(event, "event")
        es = self.entries()
        preds = [e for e in es if e["type"] == "prediction" and e["body"]["event"] == event]
        if not preds:
            raise LedgerError(f"no predictions for event {event!r}")
        for p in preds:
            if outcome not in p["body"]["probs"]:
                raise LedgerError(f"outcome {outcome!r} is not one of {list(p['body']['probs'])} (prediction {p['body']['id']!r})")
        if any(e["type"] == "outcome" and e["body"]["event"] == event for e in es):
            raise LedgerError(f"event {event!r} is already resolved")
        return self._append("outcome", {"event": event, "outcome": outcome}, now)

    def closure(self, protocol_hash: str) -> dict | None:
        """The closure entry of a protocol, if the study was closed."""
        for e in self.entries():
            if e["type"] == "closure" and e["body"]["protocol"] == protocol_hash:
                return e
        return None

    def _refuse_if_closed(self, protocol_hash: str) -> None:
        if self.closure(protocol_hash) is not None:
            raise LedgerError("this study is closed; start a new protocol (and say so) instead of adding to a closed one")

    def n_complete(self, protocol_hash: str) -> int:
        """Items (measure protocols) or resolved events (forecast protocols) recorded so far."""
        proto = self.protocols()[protocol_hash]["body"]["protocol"]
        if proto.get("kind", "forecast") == "measure":
            return len({e["body"]["item"] for e in self.entries() if e["type"] == "measurement" and e["body"]["protocol"] == protocol_hash})
        return len({r["event"] for r in self.resolved_items(protocol_hash)})

    @_atomic
    def close(self, protocol_hash: str, reason: str, kind: str | None = None, now: str | None = None) -> dict:
        """Record that a study ended, and why. A study that stops early is a result too: it stays visible.

        kind: completed | stopped_early | abandoned. Default: completed if the planned size was reached, else stopped_early.
        New predictions and measurements are refused afterwards (outcomes of earlier predictions can still be resolved).
        """
        protos = self.protocols()
        if protocol_hash not in protos:
            raise LedgerError("unknown protocol hash")
        reason = clean_text(reason, "reason")
        self._refuse_if_closed(protocol_hash)
        n = self.n_complete(protocol_hash)
        target = protos[protocol_hash]["body"]["protocol"]["n_target"]
        if kind is None:
            kind = "completed" if n >= target else "stopped_early"
        if kind not in CLOSURE_KINDS:
            raise LedgerError(f"kind must be one of {CLOSURE_KINDS}")
        if kind == "completed" and n < target:
            raise LedgerError(f"only {n} of {target} planned items are complete; close it as stopped_early or abandoned")
        return self._append("closure", {"protocol": protocol_hash, "kind": kind, "reason": reason, "n_complete": n, "n_target": target}, now)

    @_atomic
    def log_analysis(self, protocol_hash: str, kind: str, what: str, n_resolved: int, metric: str | None = None, now: str | None = None) -> dict:
        """Every look at the results is recorded, so interim peeking stays visible."""
        if protocol_hash not in self.protocols():
            raise LedgerError("unknown protocol hash")
        body = {"protocol": protocol_hash, "kind": kind, "what": clean_text(what, "analysis"), "n_resolved": n_resolved}
        if metric is not None:
            body["metric"] = clean_text(metric, "metric")
        return self._append("analysis", body, now)

    def resolved_items(self, protocol_hash: str) -> list[dict]:
        """One row per resolved prediction under a protocol."""
        es = self.entries()
        outs = {e["body"]["event"]: e["body"]["outcome"] for e in es if e["type"] == "outcome"}
        rows = []
        for e in es:
            b = e["body"]
            if e["type"] == "prediction" and b["protocol"] == protocol_hash and b["event"] in outs:
                rows.append({"id": b["id"], "event": b["event"], "forecaster": b["forecaster"], "probs": b["probs"], "outcome": outs[b["event"]]})
        return rows

    def check_manifest(self, ids: list[str]) -> list[str]:
        """Check a manifest file's ids against the sealed manifest(s) and against what was recorded.

        Problems: the set does not match any sealed manifest, or an item was recorded that is not in the set.
        (Items in the set that are not recorded yet are normal and not reported as problems.)
        """
        m = self.manifest_of(ids)
        want = set(ids)
        matches = [h for h, e in self.protocols().items() if (e["body"].get("manifest") or {}).get("sha256") == m["sha256"]]
        if not matches:
            return ["no protocol was sealed with this manifest (the item set differs from the sealed one)"]
        problems = []
        for e in self.entries():
            b = e["body"]
            if e["type"] == "measurement" and b["protocol"] in matches and b["item"] not in want:
                problems.append(f"entry {e['seq']}: item {b['item']!r} was recorded but is not in the sealed manifest")
            if e["type"] == "prediction" and b["protocol"] in matches and b["event"] not in want:
                problems.append(f"entry {e['seq']}: event {b['event']!r} was predicted but is not in the sealed manifest")
        return problems

    # ---------- verification ----------
    def verify(self, expected_head: str | None = None) -> list[str]:
        """Return a list of problems (empty list = the ledger is intact).

        ``expected_head``: a head hash you saved earlier (published or timestamped). If it is not
        in the chain, entries were removed or rewritten.
        """
        problems: list[str] = []
        prev = GENESIS
        last_ts = ""
        protos: set[str] = set()
        pred_ids: set[str] = set()
        pred_events: dict[str, list[dict]] = {}
        resolved: set[str] = set()
        hashes: set[str] = set()
        protocol_kinds: dict[str, str] = {}
        protocol_metric_names: dict[str, list[str]] = {}
        closed: set[str] = set()
        measured: set[tuple] = set()
        for i, e in enumerate(self.entries(), 1):
            try:
                if e.get("seq") != i:
                    problems.append(f"entry {i}: seq is {e.get('seq')}, expected {i}")
                if e.get("prev") != prev:
                    problems.append(f"entry {i}: prev hash does not match the previous entry")
                want = entry_hash(e.get("seq"), e.get("type"), e.get("ts"), e.get("prev"), e.get("body"))
                if e.get("hash") != want:
                    problems.append(f"entry {i}: content does not match its hash (edited?)")
                ts = e.get("ts") or ""
                if ts < last_ts:
                    problems.append(f"entry {i}: timestamp goes backwards")
                last_ts = max(last_ts, ts)
                prev = e.get("hash", "")
                hashes.add(prev)
                t, b = e.get("type"), e.get("body") or {}
                if t == "protocol":
                    protos.add(e.get("hash"))
                    protocol_kinds[e.get("hash")] = (b.get("protocol") or {}).get("kind", "forecast")
                    try:
                        protocol_metric_names[e.get("hash")] = [m["name"] for m in protocol_metrics(b.get("protocol") or {})]
                    except Exception:
                        protocol_metric_names[e.get("hash")] = []
                elif t == "prediction":
                    if b.get("protocol") in closed:
                        problems.append(f"entry {i}: prediction added after the study was closed")
                    if b.get("protocol") not in protos:
                        problems.append(f"entry {i}: prediction refers to an unregistered protocol")
                    elif protocol_kinds.get(b.get("protocol")) == "measure":
                        problems.append(f"entry {i}: prediction under a measure protocol")
                    if b.get("id") in pred_ids:
                        problems.append(f"entry {i}: duplicate prediction id {b.get('id')!r}")
                    if b.get("event") in resolved:
                        problems.append(f"entry {i}: prediction made after its event {b.get('event')!r} was resolved")
                    pred_ids.add(b.get("id"))
                    pred_events.setdefault(b.get("event"), []).append(b)
                elif t == "outcome":
                    ev = b.get("event")
                    if ev not in pred_events:
                        problems.append(f"entry {i}: outcome for an event with no predictions")
                    elif ev in resolved:
                        problems.append(f"entry {i}: event {ev!r} resolved twice")
                    elif any(b.get("outcome") not in p.get("probs", {}) for p in pred_events[ev]):
                        problems.append(f"entry {i}: outcome is not a possible outcome of every prediction")
                    resolved.add(ev)
                elif t == "measurement":
                    if b.get("protocol") in closed:
                        problems.append(f"entry {i}: measurement added after the study was closed")
                    pk = protocol_kinds.get(b.get("protocol"))
                    if pk is None:
                        problems.append(f"entry {i}: measurement refers to an unregistered protocol")
                    elif pk != "measure":
                        problems.append(f"entry {i}: measurement under a forecast protocol")
                    names = protocol_metric_names.get(b.get("protocol"), [])
                    if len(names) > 1 and b.get("metric") not in names:
                        problems.append(f"entry {i}: measurement has an unknown or missing metric")
                    key = (b.get("protocol"), b.get("item"), b.get("system"), b.get("metric"))
                    if key in measured:
                        problems.append(f"entry {i}: duplicate measurement for {b.get('system')!r} on {b.get('item')!r}")
                    measured.add(key)
                    if not _is_number(b.get("value")):
                        problems.append(f"entry {i}: measurement value is not a finite number")
                elif t == "closure":
                    if b.get("protocol") not in protos:
                        problems.append(f"entry {i}: closure refers to an unregistered protocol")
                    elif b.get("protocol") in closed:
                        problems.append(f"entry {i}: study closed twice")
                    if b.get("kind") not in CLOSURE_KINDS:
                        problems.append(f"entry {i}: unknown closure kind {b.get('kind')!r}")
                    closed.add(b.get("protocol"))
                elif t == "analysis":
                    if b.get("protocol") not in protos:
                        problems.append(f"entry {i}: analysis refers to an unregistered protocol")
                else:
                    problems.append(f"entry {i}: unknown type {t!r}")
            except Exception as ex:  # malformed entry shapes must not crash verification
                problems.append(f"entry {i}: malformed ({type(ex).__name__})")
        if expected_head and expected_head != GENESIS and expected_head not in hashes:
            problems.append("the expected head hash is not in the chain (entries removed or rewritten)")
        return problems

    def status(self) -> dict:
        es = self.entries()
        ps = [e for e in es if e["type"] == "prediction"]
        events = {e["body"]["event"] for e in ps}
        done = {e["body"]["event"] for e in es if e["type"] == "outcome"}
        return {"entries": len(es), "protocols": len(self.protocols()), "predictions": len(ps), "events": len(events),
                "resolved_events": len(done), "open_events": len(events - done),
                "measurements": sum(1 for e in es if e["type"] == "measurement"),
                "closed_studies": sum(1 for e in es if e["type"] == "closure"),
                "analyses": sum(1 for e in es if e["type"] == "analysis"), "head": self.head()}
