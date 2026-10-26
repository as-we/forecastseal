# forecastseal

Seal your evaluation plan before the results exist, keep forecasts and scores in a tamper-evident ledger, then test the comparison honestly.

> **Status: pre-alpha (v0.0.9), not on PyPI yet.** The command line, the ledger format and the report may still change.

## See it in 30 seconds

```bash
python examples/noise_demo.py
```

```text
2000 studies, no real effect anywhere, 200 items, 20 metrics each:
  one metric named in advance ........... 'significant' in  4.8% of studies  (as designed: 5%)
  best of 20, reported as if it were the only one: 66.3% of studies  (1 - 0.95^20 = 64.2%)
  best of 20, but paying for the 20 tries:  6.0% of studies
```

Nothing real is going on in that data. Reporting the best of many tries can still look like a discovery. `forecastseal` is a small tool for making that kind of process visible. For a second demo, `examples/peeking_demo.py` shows what looking early and stopping when it looks good does to false alarms and to estimates.

## The idea

Many mistakes in forecasting and in evaluating models or prompts may come less from the maths than from the process: the metric is picked after seeing the numbers, the sample is too small to see anything, or the best of twenty variants is reported as if it were the only one tried.

`forecastseal` makes the process explicit and checkable:

1. **Seal the plan first.** Metrics (which ones count as conclusions, which are exploratory), planned sample size, significance level, optional non-inferiority margin and the list of items to evaluate are written to the ledger before any result.
2. **Append, never edit.** Every entry contains the hash of the previous one. Changing, deleting or reordering history breaks the chain and `fseal verify` says so.
3. **Look at the data in a way that leaves a trace.** Comparisons use paired items and bootstrap intervals. Looking before the planned sample size needs `--interim`, is recorded, and never produces a verdict. Every look is in the ledger.
4. **Report what happened.** One self-contained HTML file with the sealed plan, scores, calibration, comparisons and the log of looks.

It is small (standard library only), runs locally and makes no network calls.

## Why now?

Two things may have changed with LLMs. Trying one more analysis became almost free, so the number of paths taken through a dataset can grow without anyone noticing. And more people can now run an analysis, or evaluate a prompt or a model, without the habits statisticians built for exactly this situation: write the plan first, count what you tried, keep some data unseen.

`forecastseal` does not make an LLM smarter. It aims to make the process visible and harder to bend by accident. That applies whether the analyst is a person, an AI agent, or both, and also when what you are analysing is an LLM-based system itself (prompts, models, judges), which is data analysis too.

## What this gets you

| Without it, this can happen | With it |
|---|---|
| "v2 looks better", after twenty variants were tried and the best one kept | The plan says what will be compared. Every look is logged, exploratory metrics are labelled and unadjusted, and the report warns when more final comparisons were run than planned. |
| The metric, threshold or margin is chosen after seeing the numbers | They are sealed before the first result. Changing any of them changes the hash. |
| The test set is quietly swapped or grown until it works | The item list is sealed by hash; `fseal verify --manifest` finds anything recorded outside it. |
| "Not significantly different, so the cheaper model is as good" | A non-inferiority margin is sealed in advance and the output says whether it is cleared. |
| Stopping early because the numbers look good | Looking before the planned sample size needs `--interim`, is recorded, and gives no verdict. |
| Past forecasts are edited or dropped when they turn out badly | The chain breaks and `verify` reports it. Anchor the head hash to catch deleted tails too. |
| Too few items to ever see the difference you care about | `fseal power` says so before you collect the data. |
| An LLM judge is trusted without checking it against people | `fseal agreement` gives kappa and AC1 with an interval. |

It cannot make a bad evaluation good. It makes the process hard to bend unnoticed, including by yourself.

**Typical uses:** choosing between two prompts or models on a fixed test set; showing a cheaper model is not worse by more than an agreed margin; tracking personal or team forecasts with honest calibration; checking an LLM judge against human labels.

## Install

```bash
git clone <this repository> && cd forecastseal
pip install -e .          # Python 3.10 or newer
fseal --version
```

## A 60-second tour: probability forecasts

```bash
fseal init
cat > protocol.json <<'JSON'
{"name": "my-forecasts", "metric": "log_loss", "n_target": 100, "alpha": 0.05}
JSON
fseal register protocol.json            # prints the protocol hash

# two forecasters predict the same event; the outcome comes later
fseal predict --id q1-A --event q1 --forecaster A --probs '{"yes":0.7,"no":0.3}'
fseal predict --id q1-B --event q1 --forecaster B --probs '{"yes":0.6,"no":0.4}'
fseal resolve q1 yes

fseal verify
fseal head                              # publish or timestamp this hash; later: fseal verify --expected-head <hash>
fseal power --sd 0.085 --delta 0.004    # how many events would it take to see a difference this small?
fseal score && fseal calibration --forecaster A
fseal test A B                          # refused before n_target unless --interim
fseal report -o report.html --compare A B
```

`examples/synthetic_demo.py` builds a complete ledger and report from synthetic data. `examples/noise_demo.py` illustrates why sealing may matter: in a simulation with no real effect anywhere, reporting the best of 20 metrics found something "significant" in about two studies out of three (1 − 0.95²⁰ ≈ 64% in theory), while one metric named in advance did so about 5% of the time.

## Comparing versions of a system (measured values)

Not everything is a probability. To compare two prompts, models or settings on the same items, seal a protocol of kind `measure`, record one score per system and item, and compare with the same rules:

```bash
cat > protocol.json <<'JSON'
{"name": "prompt-versions", "kind": "measure", "n_target": 100, "alpha": 0.05,
 "metrics": [
   {"name": "errors",   "direction": "lower_is_better",  "primary": true},
   {"name": "coverage", "direction": "higher_is_better", "primary": true},
   {"name": "style",    "direction": "higher_is_better", "primary": false}]}
JSON
fseal register protocol.json --manifest test_items.txt     # also seals the list of items to be evaluated
fseal import-csv scores.csv --wide                          # item,system,errors,coverage,style
fseal test v2 v1                                            # every metric; difference is v2 minus v1
fseal report -o report.html --compare v2 v1
```

- **Primary** metrics share the error budget: each interval uses `alpha / (primary metrics × planned comparisons)`. **Exploratory** metrics get no adjustment and are labelled as such everywhere.
- **Evaluation set.** `--manifest` seals the hash and count of the item ids (never the items). `fseal verify --manifest test_items.txt` later checks that the set is the same and that nothing outside it was recorded.
- **Non-inferiority.** "Not significantly different" is not "as good". Seal a `"margin"` (in the metric's units, chosen before looking) and `fseal test cheap big` also says whether the interval clears it.
- **Judge vs people.** Record integer labels from each rater as measurements, then `fseal agreement human llm-judge --weights quadratic` prints observed agreement, Cohen's kappa with an interval, Gwet's AC1 and the confusion table. Decide the acceptable level before looking.
- **Importing.** `fseal import-csv` (long or `--wide`) and `fseal measure --file x.jsonl` are all-or-nothing: if one row is invalid, nothing is written and the message names the rows. `--skip-existing` makes re-runs safe.
- A re-run of a system on an item is a new system name (`v2-run2`); measurements are append-only. The scores come from whatever scorer you trust. `forecastseal` does not judge them; it keeps the comparison honest. `examples/prompt_versions_demo.py` shows the flow with synthetic scores.

## If a study stops early

Stopping early is fine; treating the numbers at that moment as a result is the risky part (see `examples/peeking_demo.py`). Record it:

```bash
fseal close --reason "ran out of time"      # stopped_early / completed / abandoned
fseal report -o report.html
```

The ledger keeps the reason and the point it stopped at, refuses new data for a closed study, and the report says what the partial numbers can and cannot tell you. Looks planned in advance are a different matter: a sequential design (for example with a library such as evalsig) is the principled way to allow early stopping.

## Using it from an AI agent

[`docs/for-llm-agents.md`](docs/for-llm-agents.md) has a block you can paste into an agent's instructions so that it seals a plan, records its looks and reports how many variants it tried.

## Do you have enough data? (`fseal plan` and a one-page calculator)

Splitting data into explore / validate / confirm is pointless if the final part is too small to show anything. Ask first:

```bash
fseal plan --n-total 300 --delta 0.01 --sd 0.085          # scores: smallest difference you care about, and its spread
fseal plan --n-total 500 --rates 0.70 0.80                # pass/fail rates
```

```
The final test needs about 568 items.
You have 300 items. Split 50/20/30 gives:
  confirm       90 items   chance of seeing the difference: 20%   smallest difference you could see: 0.0251
Final test: you would have 16% of the 568 items it needs.
Verdict: not enough data. Even all 300 items would be 53% of what the final test needs. ...
```

If there is not enough data, the honest options are to collect more going forward (prospectively), to accept a larger smallest difference, or to treat every result as a hint and say so.

[`docs/plan-calculator.html`](docs/plan-calculator.html) is the same calculation as a single offline page (English and Japanese, no network, no install): open it in a browser.

## Reading the statistics honestly

- Intervals are percentile bootstrap intervals over items. With fewer than a few hundred items they can be too narrow ([Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints](https://arxiv.org/pdf/2503.01747)); `test` warns below 30 items.
- Power uses a normal approximation. Treat it as a planning guide.
- Planning several comparisons? Put the number in the protocol (`n_comparisons`). Running more final comparisons than planned prints a warning, and the report says so.

## What it does not prove

Timestamps come from your local clock. The chain proves the ledger was **not changed after you publish or anchor its head hash somewhere you do not control** (a Git push, a timestamp service such as OpenTimestamps). It cannot prove when entries were first written, and deleting the *last* entries is only detectable if you saved an earlier head hash. Anchoring is planned as an optional step. See [SECURITY.md](SECURITY.md).

## Related projects

Other tools cover parts of this well. This list reflects their package summaries and READMEs at the time of writing; check their documentation for details.

| Project | What it does | How forecastseal differs |
|---|---|---|
| [evalsig](https://pypi.org/project/evalsig/), [errorbars](https://pypi.org/project/errorbars/), [evalci](https://pypi.org/project/evalci/), [abeval](https://pypi.org/project/abeval/) | Statistics for LLM evaluations: paired tests, clustered errors, power, (evalsig) sequential testing | Richer statistics than here. They do not seal a plan or keep a ledger. Use them if statistics are all you need. |
| [calikit](https://pypi.org/project/calikit/) | Calibration auditing of probability forecasts | Deeper calibration tools; no sealing or ledger. |
| [llm-audit-trail](https://pypi.org/project/llm-audit-trail/) | Tamper-evident audit trails for LLM lifecycles | Hash-chained logging for governance; no evaluation statistics. |
| [Fatebook](https://github.com/Sage-Future/fatebook) | A friendly app for personal predictions with Brier scores | An app, not a protocol; no sealed plan. |
| [prereg-ledger](https://github.com/HarperZ9/prereg-ledger) | Public hashes of study plans, using Git push time as the outside timestamp | Hashes plans only; no forecasts, scores or comparisons. |
| [OpenTimestamps](https://opentimestamps.org) | Third-party timestamp proofs | The natural way to anchor a head hash. |

What `forecastseal` adds is the **connection**: sealed plan, append-only records, a record of every look, and a comparison under the rules you sealed, in one small local tool.

## Development

```bash
uv run --python 3.12 --with pytest pytest -q
```

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Security notes: [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
