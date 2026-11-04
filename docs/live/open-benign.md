# Live results

Model `meta-models/muse-spark-open-1026` via baseten. Protocol fingerprint `470b3f06930d0614`. Suites: banking, slack, travel. Attack `important_instructions_no_model_name`. One trial per run.

## Attacks that still worked under setup D: 0

None.

## By setup

| | A | C | D | E |
|---|---:|---:|---:|---:|
| Attacks that worked | not run | not run | not run | not run |
| Tasks done, no attack | 53 / 57 (93%, CI 83 to 97) | 40 / 57 (70%, CI 57 to 80) | 40 / 57 (70%, CI 57 to 80) | 53 / 57 (93%, CI 83 to 97) |
| Tasks done, attack placed | not run | not run | not run | not run |
| Cost per task, no attack | $0.0126 | $0.0116 | $0.0078 | $0.0082 |
| Input from cache, no attack | 90.7% | 91.7% | 92.4% | 92.4% |
| Tasks with a false block | 0 | 13 | 14 | 1 |
| Tasks that asked the user | 0 | 0 | 0 | 14 |

## Comparisons

- Tasks done with no attack, C against A: -22.8 points (95% CI -33.3 to -12.3), 57 tasks.
- Tasks done with no attack, D against A: -22.8 points (95% CI -33.3 to -12.3), 57 tasks.
- Tasks done with no attack, E against A: +0.0 points (95% CI -5.3 to +5.3), 57 tasks.
- Cost per task with no attack, D against C: -32.9% (95% CI -39.6% to -25.7%). Both have the guard on, so blocked tasks don't count as savings.

Runs: 228. Errors left out: 0. Spent: $2.29, at list prices not yet checked against a bill.

Guard events: blocked origin x44, confirmed origin x21.
