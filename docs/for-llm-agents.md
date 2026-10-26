# Using forecastseal from an AI coding agent

Paste the block below into your agent's instructions (for example `AGENTS.md` or `CLAUDE.md`), or into the first message of a session. It asks the agent to leave a trace of how many things it tried, which is the part of an AI-assisted analysis that tends to go missing from the final write-up.

It does not make the agent's analysis correct. It makes the process easier to check.

````text
## Evaluation rules (forecastseal)

When I ask you to compare options (prompts, models, settings) or to check whether something works:

1. BEFORE looking at any results, write a protocol and seal it:
   - the metric(s) that decide the question (at most 2, marked "primary") and their direction
   - any other metrics, marked "primary": false (exploratory: ideas only, not conclusions)
   - the planned number of items (`n_target`), alpha 0.05, and a non-inferiority "margin" if the question is "not worse than"
   - the list of items to evaluate (`--manifest`)
   Run: `fseal init` then `fseal register protocol.json --manifest items.txt`. Show me the protocol hash.
2. Record every score with `fseal measure` / `fseal import-csv`. Never edit or delete the ledger by hand.
3. Do not change the metrics, the item list or the sample size after sealing. If a change seems necessary, say so, and start a NEW protocol; report both.
4. Before the planned number of items is complete, use `fseal test --interim` only if I ask, and call the output "interim, not a result".
5. If we stop early, run `fseal close --reason "<why>"` and report the study as stopped early.
6. Finish with `fseal verify` and `fseal report -o report.html --compare NEW OLD`. In your summary, state: how many variants were tried, which metrics were primary, and whether the interval excludes 0. Do not describe exploratory metrics as findings.
7. Run code for every calculation and paste the output. Do not estimate numbers in your head.
8. Before splitting data, run `fseal plan --n-total N --delta D --sd S` and tell me if there is not enough data.
````

## What each rule is for

| Rule | The failure it targets |
|---|---|
| 1, 3 | Choosing the metric or threshold after seeing the numbers |
| 2 | Quietly editing or dropping records |
| 4, 5 | Looking early and stopping when the numbers look good |
| 6 | Reporting the best of many tries as if it were the only one |
| 7 | Numbers that were never computed |
| 8 | Splitting data that is too small to show anything |

## Limits

- An agent can ignore these instructions, or run its own analysis outside the ledger. The ledger records what went through it; it cannot see what did not.
- If the agent can read the held-back data, sealing does not stop it from being used. Keep that data in a place the agent cannot open.
- Hash chaining shows the ledger was not changed *after* you save its head hash somewhere the agent cannot write (`fseal head`). Save it yourself.
