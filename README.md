# forecastseal

Seal your analysis plan before the outcome is known, append forecasts to a tamper-evident ledger, then score and test them honestly.

> **Status: pre-alpha (v0.0.4).** Working: the ledger (`init`, `register`, `predict`, `resolve`, `verify`), scoring (`score`, `calibration`), paired comparison with an interval (`test`), power planning (`power`) and a self-contained HTML report (`report`).
> Also working: continuous-valued measurements for comparing versions of a system on the same items. Planned: optional OpenTimestamps anchoring.

## Why

Most forecasting and LLM evaluation mistakes are not maths mistakes. They are process mistakes: the metric was chosen after seeing the results, the sample was too small to detect anything, or the best of twenty variants was reported as if it were the only one tried.

`forecastseal` makes the process explicit:

1. **Seal the plan first.** Metric, target sample size and significance level are written to the ledger before any forecast.
2. **Append, never edit.** Each entry includes the hash of the previous one. Changing, deleting or reordering an earlier entry breaks the chain and `fseal verify` reports it.
3. **Resolve later.** Outcomes are separate entries. A prediction cannot be overwritten and an outcome cannot be changed.
4. **Score and test.** Proper scoring rules (log loss, Brier), calibration, paired comparisons with bootstrap intervals, and a power calculation you can run before looking. Every `test` run is logged in the ledger; looking before the planned sample size is allowed only with `--interim`, is recorded, and never produces a verdict.

## Quick start

```bash
pip install -e .            # from a clone; not on PyPI yet
fseal init
cat > protocol.json <<'JSON'
{"name": "my-forecasts", "metric": "log_loss", "n_target": 100, "alpha": 0.05, "n_comparisons": 1}
JSON
fseal register protocol.json          # prints the protocol hash

# two forecasters predict the same event; the outcome comes later
fseal predict --id q1-A --event q1 --forecaster A --probs '{"yes":0.7,"no":0.3}'
fseal predict --id q1-B --event q1 --forecaster B --probs '{"yes":0.6,"no":0.4}'
fseal resolve q1 yes

fseal verify
fseal head                             # publish or timestamp this hash, then later:
fseal verify --expected-head <that hash>

fseal power --sd 0.085 --delta 0.004   # how many events are needed to see a difference this small
fseal score                            # mean loss per forecaster
fseal calibration --forecaster A       # reliability table and ECE
fseal test A B                         # paired comparison; refuses before n_target unless --interim
fseal report -o report.html --compare A B   # one HTML file: scores, calibration, comparison, analysis log
```

A runnable synthetic example (no real-world data) is in `examples/synthetic_demo.py`; it also writes `demo_report.html`.

The report is a single HTML file with no scripts and no external requests (a strict Content-Security-Policy is embedded; every string from the ledger is escaped). If the hash chain does not verify, the report says so at the top. Asking for a comparison in the report follows the same rules as `fseal test` (refused before `n_target` unless `--interim`; every look is logged).

## Comparing versions of a system (measured values)

Not everything is a probability forecast. To compare two prompts, two models or two settings on the same items, seal a protocol of kind `measure`, record one score per system and item, and compare them with the same rules (paired items, intervals, sample size fixed in advance, looks logged):

```bash
cat > protocol.json <<'JSON'
{"name": "prompt-versions", "kind": "measure", "metric": "quality score",
 "direction": "higher_is_better", "n_target": 40, "alpha": 0.05}
JSON
fseal init && fseal register protocol.json
fseal measure --item doc-01 --system v1 --value 0.62
fseal measure --item doc-01 --system v2 --value 0.71      # or --file scores.jsonl
fseal score                       # mean per system
fseal test v2 v1                  # positive favours v2 because higher is better
fseal report -o report.html --compare v2 v1
```

A re-run of a system on an item is a new system name (`v2-run2`): measurements are append-only. `examples/prompt_versions_demo.py` shows the whole flow with synthetic scores. The scores themselves come from whatever scorer you trust; `forecastseal` does not judge them, it keeps the comparison honest.

## Reading the statistics honestly
- Intervals are percentile bootstrap intervals over events. With fewer than a few hundred events they can be too narrow ([Position: Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints](https://arxiv.org/pdf/2503.01747)); `test` warns below 30 events.
- Power uses a normal approximation. Treat it as a planning guide.
- If you plan several comparisons, put the number in the protocol (`n_comparisons`); the interval is widened accordingly (Bonferroni). Running more final comparisons than planned prints a warning.

## What it does not prove

The timestamps come from your local clock. The chain proves the ledger was **not edited after you publish or anchor its head hash somewhere you do not control** (for example a Git push, or a timestamp service such as OpenTimestamps). It cannot prove when entries were first written. Anchoring is planned as an optional step.

## Related projects

These are different in scope; use them if they fit better.

- [Fatebook](https://github.com/Sage-Future/fatebook): a friendly app for personal predictions, with Brier scores and calibration charts.
- [errorbars](https://pypi.org/project/errorbars/), [abeval](https://pypi.org/project/abeval/): statistics for LLM evaluation (intervals, paired tests, power).
- [OpenTimestamps](https://opentimestamps.org): third-party timestamp proofs.
- [prereg-ledger](https://github.com/HarperZ9/prereg-ledger): public hashes of study plans using Git push time as the outside timestamp.

`forecastseal` aims to connect the sealing, the append-only forecasts and the evaluation statistics in one small tool that runs locally.

## Security

See [SECURITY.md](SECURITY.md) for what the ledger does and does not protect against.

## Development

```bash
uv run --python 3.12 --with pytest pytest -q
```

## License

MIT. See [LICENSE](LICENSE).
