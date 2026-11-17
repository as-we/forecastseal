# Changelog

## Unreleased (0.0.11)
- Stages: a protocol can declare `stage` (explore / validate / confirm) and `after` (the earlier stage or stages). Within one chain of stages an item may be used by one stage only: sealing a manifest that reuses one, or recording one, is refused, and `verify` re-checks the whole history.
- Groups: `group_by` keeps whole groups (case, speaker, period, source) apart between stages. Records carry a `group` (`measure --group`, JSONL `"group"`, `import-csv --group-col`, `predict --group`). A manifest can map items to groups (`item<TAB>group` lines or a JSON object); the map is sealed by hash and `verify --manifest` checks recorded groups against it.
- Sealed candidates: `systems` limits which systems (or forecasters) a protocol accepts.
- `fseal overlap`: list the candidate items or groups already used in a linked stage, and write the usable rest.
- `--by KEY` for `score`, `test` and `report`: split by the recorded group or by a key of the recorded `meta`. Split comparisons are exploratory, unadjusted, never verdicts, and logged.
- The report shows the stage, the linked stages, the groups kept apart and the sealed candidates.
- `examples/stages_demo.py`.

## 0.0.10
First tagged state. Everything below is new.
- Hash-chained, append-only ledger: `init`, `register`, `predict`, `resolve`, `measure`, `verify`, `status`, `head`.
- Scoring and tests: `score`, `calibration`, `test` (paired bootstrap, looks logged, `--interim`), `power`.
- Several metrics per protocol (primary / exploratory), non-inferiority margin, `agreement` (kappa, AC1).
- Sealed evaluation sets (`--manifest`), CSV and JSONL import, all-or-nothing bulk recording.
- Self-contained HTML report (`report`).
- Fix: readers now take the ledger lock too, and every read-check-append operation holds it for its whole sequence, so a reader can no longer see a half-written last line while another process appends (seen as a flaky failure on a CI runner). Deterministic regression test added.
- Report: a timeline of looks (x for a look before the planned size, a filled circle for a final analysis, a marker where a study stopped). `examples/sample_report.py`, `docs/sample-report.html`, README figures.
- `fseal close`: record that a study ended (completed / stopped early / abandoned) and why; closed studies refuse new data; the report says what partial numbers can and cannot tell. `examples/peeking_demo.py`. `docs/for-llm-agents.md`.
- `examples/noise_demo.py`: how often pure noise looks like a discovery, and how exploratory metrics are labelled.
- `fseal plan` (is there enough data to split into explore / validate / confirm?) and an offline calculator page, `docs/plan-calculator.html`.
