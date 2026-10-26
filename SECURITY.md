# Security notes

`forecastseal` is a local command-line tool. It makes no network calls, runs no subprocesses, and has no
third-party runtime dependencies. It never uses `eval`, `pickle` or shell commands.

## What the ledger protects against
- **Editing, deleting or reordering an earlier entry**: every entry commits to the previous hash, so `fseal verify` reports it.
- **Overwriting a forecast or changing an outcome**: refused by the API, and flagged by `verify` if the file was edited by hand.
- **Predicting after the outcome is known**: refused, and flagged by `verify`.
- **Concurrent writers forking the chain**: appends take an exclusive file lock and are flushed with `fsync`.
- **Reports**: `fseal report` writes one HTML file with no JavaScript and no external requests, a restrictive Content-Security-Policy, and HTML-escaped ledger text; a broken chain is shown at the top of the report.
- **Hostile input**: names, ids and labels reject control characters (terminal escape sequences) and are length-limited; NaN and Infinity are refused; lines over 1 MB are refused; malformed entries make `verify` report a problem instead of crashing.

## What it does not protect against (by design)
- **Someone who can rewrite the whole file** can recompute every hash. Defence: save or publish the head hash (`fseal head`) somewhere you do not control (a Git push, a timestamp service) and later run `fseal verify --expected-head <hash>`. Without an earlier head, deleting the *last* entries cannot be detected.
- **Timestamps** come from the local clock and are not proof of when an entry was written. `verify` only checks that they never go backwards.
- **No encryption or access control**: the ledger is a plain text file. Do not put secrets in forecast metadata.
- **Very large files** are read into memory; this is a personal-scale tool.
- The bootstrap uses Python's `random` (seeded, for reproducibility). It is not cryptographic and does not need to be.

## Checks run
`bandit` (static analysis; one low-severity note on `random`, explained above), `pip-audit` (no dependencies), 40 tests including tamper, truncation, concurrency, hostile-input and report-injection cases.

## Reporting
Please open a private security advisory on the repository, or an issue if it is not sensitive.
