# Contributing

Thanks for looking. This is a small project with one rule that matters: **keep it small and honest.**

- The runtime has **no third-party dependencies**; please keep it that way. Dev tools (pytest, bandit) are fine.
- The library knows about items, systems and numbers only. Domain-specific scorers, document formats and adapters belong in your own code that uses `forecastseal` as a library.
- Any change that touches the ledger format, the sealing rules or the statistics needs a test, including one that tries to break the rule.
- Never weaken a refusal (for example, comparing before `n_target` without `--interim`) to make something convenient.

```bash
uv run --python 3.12 --with pytest pytest -q
uv run --python 3.12 --with bandit bandit -q -r src
```

Please do not put real-world datasets in the repository. Examples use synthetic data.
