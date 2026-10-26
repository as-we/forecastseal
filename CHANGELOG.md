# Changelog

## Unreleased (0.0.9)
First tagged state. Everything below is new.
- Hash-chained, append-only ledger: `init`, `register`, `predict`, `resolve`, `measure`, `verify`, `status`, `head`.
- Scoring and tests: `score`, `calibration`, `test` (paired bootstrap, looks logged, `--interim`), `power`.
- Several metrics per protocol (primary / exploratory), non-inferiority margin, `agreement` (kappa, AC1).
- Sealed evaluation sets (`--manifest`), CSV and JSONL import, all-or-nothing bulk recording.
- Self-contained HTML report (`report`).
- `fseal close`: record that a study ended (completed / stopped early / abandoned) and why; closed studies refuse new data; the report says what partial numbers can and cannot tell. `examples/peeking_demo.py`. `docs/for-llm-agents.md`.
- `examples/noise_demo.py`: how often pure noise looks like a discovery, and how exploratory metrics are labelled.
- `fseal plan` (is there enough data to split into explore / validate / confirm?) and an offline calculator page, `docs/plan-calculator.html`.
