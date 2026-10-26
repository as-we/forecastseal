"""fseal command line."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ledger import Ledger, LedgerError


def _ledger(args) -> Ledger:
    return Ledger(args.dir)


def cmd_init(args):
    _ledger(args).init()
    print(f"initialised {args.dir}/ledger.jsonl")


def cmd_register(args):
    raw = Path(args.protocol).read_bytes()
    e = _ledger(args).register(json.loads(raw), source_bytes=raw)
    print(f"sealed protocol {e['body']['protocol']['name']!r}\nprotocol hash: {e['hash']}")


def cmd_predict(args):
    led = _ledger(args)
    if args.file:
        n = 0
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                led.predict(r["id"], r["protocol"], r.get("forecaster", "anon"), r["probs"], r.get("meta"))
                n += 1
        print(f"appended {n} predictions")
    else:
        led.predict(args.id, args.protocol, args.forecaster, json.loads(args.probs))
        print(f"appended prediction {args.id}")


def cmd_resolve(args):
    _ledger(args).resolve(args.id, args.outcome)
    print(f"resolved {args.id} -> {args.outcome}")


def cmd_verify(args):
    problems = _ledger(args).verify()
    if problems:
        print("LEDGER BROKEN")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print("ledger intact; head:", _ledger(args).head())


def cmd_status(args):
    for k, v in _ledger(args).status().items():
        print(f"{k:12s} {v}")


def cmd_head(args):
    print(_ledger(args).head())


def main(argv=None):
    p = argparse.ArgumentParser(prog="fseal", description="Seal the plan, append forecasts, resolve outcomes, verify the chain.")
    p.add_argument("--dir", default=".fseal", help="ledger directory (default .fseal)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create an empty ledger").set_defaults(fn=cmd_init)
    s = sub.add_parser("register", help="seal an analysis protocol (JSON file)"); s.add_argument("protocol"); s.set_defaults(fn=cmd_register)
    s = sub.add_parser("predict", help="append a prediction (or --file JSONL)")
    s.add_argument("--file"); s.add_argument("--id"); s.add_argument("--protocol"); s.add_argument("--forecaster", default="anon")
    s.add_argument("--probs", help='JSON, e.g. \'{"yes":0.7,"no":0.3}\''); s.set_defaults(fn=cmd_predict)
    s = sub.add_parser("resolve", help="record the outcome of a prediction"); s.add_argument("id"); s.add_argument("outcome"); s.set_defaults(fn=cmd_resolve)
    sub.add_parser("verify", help="check the hash chain").set_defaults(fn=cmd_verify)
    sub.add_parser("status", help="counts and head hash").set_defaults(fn=cmd_status)
    sub.add_parser("head", help="print the head hash (publish or timestamp it)").set_defaults(fn=cmd_head)
    args = p.parse_args(argv)
    try:
        args.fn(args)
    except LedgerError as e:
        print("error:", e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
