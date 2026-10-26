"""fseal command line."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from . import report, stats, workflow
from .ledger import Ledger, LedgerError, loads


def _ledger(args) -> Ledger:
    return Ledger(args.dir)


def _protocol_hash(led: Ledger, args) -> str:
    ps = led.protocols()
    if getattr(args, "protocol", None):
        if args.protocol not in ps:
            raise LedgerError("unknown protocol hash")
        return args.protocol
    if len(ps) == 1:
        return next(iter(ps))
    raise LedgerError("several protocols are registered; pass --protocol <hash>")


def _proto(led: Ledger, h: str) -> dict:
    return led.protocols()[h]["body"]["protocol"]


def cmd_init(args):
    _ledger(args).init()
    print(f"initialised {args.dir}/ledger.jsonl")


def _read_ids(path: str) -> list[str]:
    """One item id per line, or a JSON array of strings."""
    text = Path(path).read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        try:
            ids = loads(text)
        except ValueError as e:
            raise LedgerError(f"manifest is not valid JSON: {e}") from e
        if not all(isinstance(i, str) for i in ids):
            raise LedgerError("a JSON manifest must be an array of strings")
        return ids
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def cmd_register(args):
    raw = Path(args.protocol_file).read_bytes()
    try:
        data = loads(raw.decode("utf-8"))
    except ValueError as e:
        raise LedgerError(f"protocol file is not valid JSON: {e}") from e
    ids = _read_ids(args.manifest) if args.manifest else None
    e = _ledger(args).register(data, source_bytes=raw, manifest_ids=ids)
    print(f"sealed protocol {e['body']['protocol']['name']!r}\nprotocol hash: {e['hash']}")
    if ids is not None:
        print(f"sealed item set: {e['body']['manifest']['count']} items, sha256 {e['body']['manifest']['sha256']}")


def cmd_predict(args):
    led = _ledger(args)
    if args.file:
        n = 0
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = loads(line)
                led.predict(r["id"], r["protocol"], r.get("forecaster", "anon"), r["probs"], event=r.get("event"), meta=r.get("meta"))
                n += 1
        print(f"appended {n} predictions")
    else:
        if not (args.id and args.probs):
            raise LedgerError("give --id and --probs, or --file")
        led.predict(args.id, _protocol_hash(led, args), args.forecaster, loads(args.probs), event=args.event)
        print(f"appended prediction {args.id}")


def cmd_measure(args):
    led = _ledger(args)
    if args.file:
        n = 0
        h = _protocol_hash(led, args)
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = loads(line)
                led.measure(r["item"], r["system"], r["value"], h, metric=r.get("metric", args.metric), meta=r.get("meta"))
                n += 1
        print(f"appended {n} measurements")
    else:
        if not (args.item and args.system and args.value is not None):
            raise LedgerError("give --item, --system and --value, or --file")
        led.measure(args.item, args.system, args.value, _protocol_hash(led, args), metric=args.metric)
        print(f"recorded {args.system} on {args.item}: {args.value}")


def cmd_resolve(args):
    _ledger(args).resolve(args.event, args.outcome)
    print(f"resolved {args.event} -> {args.outcome}")


def cmd_verify(args):
    led = _ledger(args)
    problems = led.verify(expected_head=args.expected_head)
    if args.manifest:
        problems += led.check_manifest(_read_ids(args.manifest))
    if problems:
        print("LEDGER BROKEN")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print("ledger intact; head:", led.head())


def cmd_status(args):
    for k, v in _ledger(args).status().items():
        print(f"{k:16s} {v}")


def cmd_head(args):
    print(_ledger(args).head())


def cmd_score(args):
    led = _ledger(args)
    h = _protocol_hash(led, args)
    ms = [workflow.pick_metric(led, h, args.metric)] if args.metric else workflow.metrics_of(led, h)
    for m in ms:
        res = stats.score(led.items_for(h, m["name"]), m["name"])
        tag = "" if len(ms) == 1 else (" [primary]" if m["primary"] else " [exploratory]")
        print(f"metric: {m['name']}{tag} ({workflow.direction_text(m['direction'])})")
        hib = m["direction"] == "higher_is_better"
        for name, r in sorted(res.items(), key=lambda kv: -kv[1]["mean"] if hib else kv[1]["mean"]):
            print(f"  {name:24s} n={r['n']:<5d} mean={r['mean']:.4f}")


def cmd_calibration(args):
    led = _ledger(args)
    h = _protocol_hash(led, args)
    rows = [r for r in led.items_for(h) if not args.forecaster or r["forecaster"] == args.forecaster]
    try:
        cal = stats.calibration(rows)
    except ValueError as e:
        raise LedgerError(str(e)) from e
    print(f"pairs: {cal['n']}   ECE: {cal['ece']:.4f}   (bins with few pairs are noise)")
    print("  bin          n   mean_pred   observed")
    for b in cal["bins"]:
        print(f"  {b['lo']:.1f}-{b['hi']:.1f}  {b['n']:6d}   {b['mean_pred']:.3f}       {b['freq']:.3f}")


def _print_comparison(res: dict) -> None:
    lo, hi = res["ci"]
    a, b = res["a"], res["b"]
    sign = f"positive favours {a}" if res["higher_is_better"] else f"negative favours {a}"
    role = ""
    if res["multi"]:
        role = " [primary]" if res["primary"] else " [exploratory: no multiplicity adjustment; do not draw conclusions]"
    print(f"{a} vs {b}  ({res['metric']}{role}; difference = {a} minus {b}; {sign})")
    print(f"  paired items: {res['n']}   mean difference: {res['mean_diff']:+.4f}   sd: {res['sd']:.4f}")
    print(f"  {100 * (1 - res['alpha_adj']):.2f}% interval (alpha {res['alpha']} / {res['family']} in the confirmatory family): [{lo:+.4f}, {hi:+.4f}]")
    if res["n"] < 30:
        print("  warning: fewer than 30 paired items; intervals are unreliable at this size")
    if not res["final"]:
        print("  INTERIM LOOK, not a verdict. This look is recorded in the ledger.")
    else:
        print("  verdict:", f"interval excludes 0; {res['better']} is better" if res["excludes_zero"] else "interval includes 0: no difference shown")
        if res["prior_final"] >= res["planned"]:
            print(f"  warning: this is final analysis #{res['prior_final'] + 1} for this metric, but the protocol planned {res['planned']} comparison(s). Treat the interval as too narrow.")


def cmd_test(args):
    led = _ledger(args)
    h = _protocol_hash(led, args)
    names = [args.metric] if args.metric else [m["name"] for m in workflow.metrics_of(led, h)]
    for k, name in enumerate(names):
        if k:
            print()
        _print_comparison(workflow.compare_logged(led, h, args.a, args.b, interim=args.interim, seed=args.seed, metric=name))


def cmd_report(args):
    led = _ledger(args)
    h = _protocol_hash(led, args)
    pairs = [tuple(c) for c in (args.compare or [])]
    page = report.build(led, h, compare=pairs, interim=args.interim, seed=args.seed)
    out = Path(args.output)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(page) // 1024} KB, self-contained: no scripts, no external requests)")


def cmd_power(args):
    sd = args.sd
    if args.from_ledger:
        led = _ledger(args)
        h = _protocol_hash(led, args)
        a, b = args.from_ledger
        m = workflow.pick_metric(led, h, args.metric)
        d = stats.paired_diffs(led.items_for(h, m["name"]), m["name"], a, b)
        if len(d) < 2:
            raise LedgerError("need at least two paired events to estimate the spread")
        sd = stats.stdev(d)
        print(f"spread estimated from {len(d)} paired events: sd = {sd:.4f}")
    if sd is None or sd <= 0:
        raise LedgerError("give --sd (spread of per-event loss differences) or --from-ledger A B")
    alpha = args.alpha / args.n_comparisons
    print(f"alpha {args.alpha} / {args.n_comparisons} comparison(s) = {alpha:.4f}, two-sided, normal approximation")
    if args.delta:
        print(f"chance of detecting a true improvement of {args.delta}:")
        for n in (50, 100, 200, 400, 800, 1600):
            print(f"  n={n:<5d} {100 * stats.power(n, args.delta, sd, alpha):5.1f}%")
        print(f"events needed for 80% power: {stats.required_n(args.delta, sd, alpha)}")
    if args.n:
        print(f"smallest true improvement detectable with 80% power at n={args.n}: {stats.min_detectable(args.n, sd, alpha):.4f}")
    if not (args.delta or args.n):
        raise LedgerError("give --delta and/or --n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="fseal", description="Seal the plan, append forecasts, resolve outcomes, verify, score and test.")
    p.add_argument("--dir", default=".fseal", help="ledger directory (default .fseal)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        return s

    add("init", cmd_init, "create an empty ledger")
    s = add("register", cmd_register, "seal an analysis protocol (JSON file)"); s.add_argument("protocol_file")
    s.add_argument("--manifest", help="file with the item ids to be evaluated (one per line, or a JSON array); its hash is sealed too")
    s = add("predict", cmd_predict, "append a prediction (or --file JSONL)")
    s.add_argument("--file"); s.add_argument("--id"); s.add_argument("--event"); s.add_argument("--protocol")
    s.add_argument("--forecaster", default="anon"); s.add_argument("--probs", help='JSON, e.g. \'{"yes":0.7,"no":0.3}\'')
    s = add("measure", cmd_measure, "record a score of a system on an item (measure protocols)")
    s.add_argument("--file", help='JSONL lines like {"item": "doc-1", "system": "v2", "value": 0.83}')
    s.add_argument("--item"); s.add_argument("--system"); s.add_argument("--value", type=float); s.add_argument("--protocol")
    s.add_argument("--metric", help="required when the protocol defines several metrics (a JSONL line may carry its own \"metric\")")
    s = add("resolve", cmd_resolve, "record the outcome of an event"); s.add_argument("event"); s.add_argument("outcome")
    s = add("verify", cmd_verify, "check the hash chain"); s.add_argument("--expected-head", help="a head hash you saved or timestamped earlier")
    s.add_argument("--manifest", help="re-check an item list against the sealed manifest and the recorded items")
    add("status", cmd_status, "counts and head hash")
    add("head", cmd_head, "print the head hash (publish or timestamp it)")
    s = add("score", cmd_score, "mean loss (or value) per forecaster or system"); s.add_argument("--protocol"); s.add_argument("--metric")
    s = add("calibration", cmd_calibration, "reliability table and ECE"); s.add_argument("--protocol"); s.add_argument("--forecaster")
    s = add("test", cmd_test, "paired comparison of two forecasters with an interval")
    s.add_argument("a"); s.add_argument("b"); s.add_argument("--protocol"); s.add_argument("--interim", action="store_true"); s.add_argument("--seed", type=int, default=43)
    s.add_argument("--metric", help="one metric (default: every metric of the protocol)")
    s = add("report", cmd_report, "write a self-contained HTML report")
    s.add_argument("-o", "--output", default="report.html"); s.add_argument("--protocol"); s.add_argument("--seed", type=int, default=43)
    s.add_argument("--compare", nargs=2, action="append", metavar=("A", "B"), help="add a paired comparison (repeatable); logged like `test`")
    s.add_argument("--interim", action="store_true")
    s = add("power", cmd_power, "how many events are needed to detect a difference")
    s.add_argument("--sd", type=float); s.add_argument("--delta", type=float); s.add_argument("--n", type=int)
    s.add_argument("--alpha", type=float, default=0.05); s.add_argument("--n-comparisons", type=int, default=1)
    s.add_argument("--from-ledger", nargs=2, metavar=("A", "B")); s.add_argument("--protocol"); s.add_argument("--metric")

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except (LedgerError, ValueError, OSError, KeyError) as e:
        print("error:", e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
