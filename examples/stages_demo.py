"""Synthetic demo: explore on some groups, then confirm on groups the exploration never saw.

The setting is made up: four detector variants label images as "made by a generator" or not; each image comes from
one of 18 generators and is shown as is, recompressed, or cropped. The question is whether the best variant still
beats the baseline on generators it was not tuned on. So the group kept apart is the generator, not only the image.

    python examples/stages_demo.py           # writes ./stages_ledger/ and stages_report.html

What it shows:
  1. explore stage: all four variants on 6 generators; pick the best one
  2. `overlap`: a candidate list for the next stage that still contains explored generators is caught
  3. confirm stage: only the sealed candidates, only unseen generators; a reused generator is refused
  4. the report, with a table split by the image condition (descriptive, not a conclusion)
"""
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forecastseal import Ledger, LedgerError, report, stats, workflow  # noqa: E402

VARIANTS = {"baseline": 0.70, "variant-a": 0.72, "variant-b": 0.78, "variant-c": 0.74}   # true accuracy on familiar generators
CONDITIONS = ("original", "recompressed", "cropped")
PER_GENERATOR = 20


def images(gens, rng):
    out = []
    for g in gens:
        hardness = rng.gauss(0, 0.06)                     # some generators are harder for every detector
        for k in range(PER_GENERATOR):
            out.append((f"{g}-img{k:02d}", g, CONDITIONS[k % 3], hardness))
    return out


def correct(rng, base, hardness, condition, unseen):
    p = base - hardness - (0.05 if condition == "cropped" else 0) - (0.04 if unseen else 0)
    return 1.0 if rng.random() < min(max(p, 0.01), 0.99) else 0.0


def main(root=Path("stages_ledger"), out=Path("stages_report.html"), seed=5):
    rng = random.Random(seed)
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    led = Ledger(root)
    led.init()
    gens = [f"gen-{i:02d}" for i in range(18)]
    explore_imgs = images(gens[:6], rng)
    base = {"kind": "measure", "metric": "correct", "direction": "higher_is_better", "alpha": 0.05, "group_by": "generator"}

    # 1. explore
    ex = led.register({**base, "name": "explore: four variants", "stage": "explore", "n_target": len(explore_imgs)},
                      manifest_groups={i: g for i, g, _, _ in explore_imgs})["hash"]
    led.measure_many(ex, [{"item": i, "system": v, "group": g, "meta": {"condition": c},
                           "value": correct(rng, acc, hard, c, unseen=False)}
                          for i, g, c, hard in explore_imgs for v, acc in VARIANTS.items()])
    means = {k: r["mean"] for k, r in stats.score(led.items_for(ex), "correct").items()}
    best = max((k for k in means if k != "baseline"), key=means.get)
    print("explore (6 generators):", ", ".join(f"{k} {v:.3f}" for k, v in sorted(means.items())), "->", best, "goes on")

    # 2. build the confirm list; a sloppy list that re-uses two explored generators is caught
    confirm_imgs = images(gens[4:], rng)                  # gen-04 and gen-05 were explored
    groups = {i: g for i, g, _, _ in confirm_imgs}
    ov = led.overlap(list(groups), [ex], groups=groups)
    print(f"overlap: {len(ov['groups'])} generator(s) already explored {ov['groups']}; {len(ov['remaining'])} of {len(groups)} images usable")
    keep = set(ov["remaining"])
    confirm_imgs = [x for x in confirm_imgs if x[0] in keep]

    # 3. confirm: sealed candidates, unseen generators only
    cf = led.register({**base, "name": "confirm: best variant vs baseline on unseen generators", "stage": "confirm", "after": ex,
                       "systems": [best, "baseline"], "n_target": len(confirm_imgs)},
                      manifest_groups={i: g for i, g, _, _ in confirm_imgs})["hash"]
    try:
        led.measure("gen-05-extra", best, 1.0, cf, group="gen-05")        # a new image, but from an explored generator
    except LedgerError as e:
        print("refused:", str(e).split(";")[0])
    led.measure_many(cf, [{"item": i, "system": v, "group": g, "meta": {"condition": c},
                           "value": correct(rng, VARIANTS[v], hard, c, unseen=True)}
                          for i, g, c, hard in confirm_imgs for v in (best, "baseline")])
    r = workflow.compare_logged(led, cf, best, "baseline")
    lo, hi = r["ci"]
    print(f"confirm (12 unseen generators, {r['n']} images): {best} minus baseline = {r['mean_diff']:+.3f}, "
          f"interval [{lo:+.3f}, {hi:+.3f}] -> " + (f"{r['better']} is better" if r["excludes_zero"] else "no difference shown"))
    print("note: images from one generator are correlated, and this interval treats them as independent, so it is too narrow. "
          "For a cluster-aware interval use a statistics library (see the README).")
    print("ledger:", "intact" if not led.verify() else "BROKEN")
    Path(out).write_text(report.build(led, cf, compare=[(best, "baseline")], by="condition"), encoding="utf-8")
    print("wrote", out)
    return led, ex, cf


if __name__ == "__main__":
    main()
