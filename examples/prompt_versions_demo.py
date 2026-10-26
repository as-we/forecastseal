"""Synthetic demo: compare two versions of a system (for example two prompts) on the same 40 documents.

Each document gets a quality score from 0 to 1 from some scorer; higher is better. Version v2 is slightly better
than v1. The protocol is sealed first, so the number of documents and the metric cannot be changed after looking.

    python examples/prompt_versions_demo.py      # writes ./versions_ledger/ and versions_report.html
"""
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forecastseal import Ledger, report, stats  # noqa: E402

root = Path("versions_ledger")
if root.exists():
    shutil.rmtree(root)
led = Ledger(root)
led.init()
h = led.register({"name": "prompt-versions", "kind": "measure", "metric": "quality score", "direction": "higher_is_better",
                  "n_target": 40, "alpha": 0.05, "n_comparisons": 1})["hash"]
rng = random.Random(11)
for i in range(40):
    difficulty = rng.gauss(0.62, 0.14)                       # shared by both versions
    led.measure(f"doc-{i:02d}", "v1", difficulty + rng.gauss(0, 0.06), h)
    led.measure(f"doc-{i:02d}", "v2", difficulty + 0.04 + rng.gauss(0, 0.06), h)
rows = led.items_for(h)
r = stats.compare(rows, "quality score", "v2", "v1", 0.05, higher_is_better=True)
print("v2 minus v1:", round(r["mean_diff"], 4), "interval", tuple(round(x, 4) for x in r["ci"]), "better:", r["better"])
print("planning: documents needed to see a 0.02 gain with this spread:", stats.required_n(0.02, r["sd"], 0.05))
Path("versions_report.html").write_text(report.build(led, h, compare=[("v2", "v1")]), encoding="utf-8")
print("wrote versions_report.html")
