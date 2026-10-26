"""What happens if you look early and stop when it looks good?

Simulated studies of up to 100 items. The analyst looks after every 10 items and stops at the first
p < 0.05. Compare with looking once, at the planned size.

    python examples/peeking_demo.py

Numbers are from a z-test approximation and are rough; the pattern is what matters.
"""
import math
import random
from statistics import NormalDist, mean, stdev

N = NormalDist()
N_MAX, LOOK_EVERY, STUDIES = 100, 10, 4000


def p_value(d):
    se = stdev(d) / math.sqrt(len(d))
    return 2 * (1 - N.cdf(abs(mean(d) / se)))


def run(effect, seed=1):
    rng = random.Random(seed)
    looks = range(LOOK_EVERY, N_MAX + 1, LOOK_EVERY)
    fixed = peek = 0
    estimates_when_stopped = []
    for _ in range(STUDIES):
        d = [rng.gauss(effect, 1) for _ in range(N_MAX)]
        fixed += p_value(d) < 0.05                       # one look, at the planned size
        stop = next((k for k in looks if p_value(d[:k]) < 0.05), None)
        if stop:                                         # stopped early because it looked significant
            peek += 1
            estimates_when_stopped.append(mean(d[:stop]))
    return fixed / STUDIES, peek / STUDIES, (mean(estimates_when_stopped) if estimates_when_stopped else float("nan"))


if __name__ == "__main__":
    f0, p0, _ = run(0.0)
    f1, p1, est = run(0.2)
    print(f"{STUDIES} simulated studies, up to {N_MAX} items, a look every {LOOK_EVERY} items\n")
    print("No real effect:")
    print(f"  one look at {N_MAX} items ............... 'significant' in {100 * f0:4.1f}% of studies")
    print(f"  stop at the first p < 0.05 ........... 'significant' in {100 * p0:4.1f}% of studies")
    print("A real effect of 0.2:")
    print(f"  one look at {N_MAX} items ............... found in {100 * f1:4.1f}% of studies")
    print(f"  stop at the first p < 0.05 ........... found in {100 * p1:4.1f}% of studies; the estimate at that point averages {est:.2f} (true value 0.20)")
    print("\nStopping is fine. Treating the numbers at the moment you stopped as a result is the risky part.")
