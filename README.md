# forecastseal

Seal your analysis plan before the outcome is known, append forecasts to a tamper-evident ledger, then score and test them honestly.

> **Status: pre-alpha (v0.0.1).** The ledger core works (`init`, `register`, `predict`, `resolve`, `verify`).
> Scoring, calibration, power analysis and the HTML report are planned, not built yet.

## Why

Most forecasting and LLM evaluation mistakes are not maths mistakes. They are process mistakes: the metric was chosen after seeing the results, the sample was too small to detect anything, or the best of twenty variants was reported as if it were the only one tried.

`forecastseal` makes the process explicit:

1. **Seal the plan first.** Metric, target sample size and significance level are written to the ledger before any forecast.
2. **Append, never edit.** Each entry includes the hash of the previous one. Changing, deleting or reordering an earlier entry breaks the chain and `fseal verify` reports it.
3. **Resolve later.** Outcomes are separate entries. A prediction cannot be overwritten and an outcome cannot be changed.
4. *(planned)* **Score and test.** Proper scoring rules (log loss, Brier), calibration, paired comparisons with intervals, power calculation before you look, and a count of how many comparisons you ran.

## Quick start

```bash
pip install -e .            # from a clone; not on PyPI yet
fseal init
cat > protocol.json <<'JSON'
{"name": "my-forecasts", "metric": "log_loss", "n_target": 100, "alpha": 0.05}
JSON
fseal register protocol.json          # prints the protocol hash
fseal predict --id q1 --protocol <protocol-hash> --probs '{"yes":0.7,"no":0.3}'
fseal resolve q1 yes
fseal verify
fseal head                             # publish or timestamp this hash
```

## What it does not prove

The timestamps come from your local clock. The chain proves the ledger was **not edited after you publish or anchor its head hash somewhere you do not control** (for example a Git push, or a timestamp service such as OpenTimestamps). It cannot prove when entries were first written. Anchoring is planned as an optional step.

## Related projects

These are different in scope; use them if they fit better.

- [Fatebook](https://github.com/Sage-Future/fatebook): a friendly app for personal predictions, with Brier scores and calibration charts.
- [errorbars](https://pypi.org/project/errorbars/), [abeval](https://pypi.org/project/abeval/): statistics for LLM evaluation (intervals, paired tests, power).
- [OpenTimestamps](https://opentimestamps.org): third-party timestamp proofs.
- [prereg-ledger](https://github.com/HarperZ9/prereg-ledger): public hashes of study plans using Git push time as the outside timestamp.

`forecastseal` aims to connect the sealing, the append-only forecasts and the evaluation statistics in one small tool that runs locally.

## Development

```bash
uv run --python 3.12 --with pytest pytest -q
```

## License

MIT. See [LICENSE](LICENSE).
