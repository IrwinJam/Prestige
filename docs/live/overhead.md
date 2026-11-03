# Time added by the gateway

Live traces, re-screened on one laptop. Counts only.

## Guard time per model reply

| Run | Replies | Median | 95th percentile | Max | Median model reply |
|---|---:|---:|---:|---:|---:|
| `main-benign` | 1100 | 0.33 ms | 1.35 ms | 2.58 ms | 3.63 s |
| `open-benign` | 948 | 0.31 ms | 1.46 ms | 3.80 ms | 1.51 s |
| `muse-autodojo` | 2181 | 0.46 ms | 2.05 ms | 3.41 ms | 5.66 s |
| `open-autodojo` | 1814 | 0.41 ms | 2.46 ms | 7.54 ms | 2.04 s |

## Model time per task, no attack

Sum of provider latency over a task's calls. Paired by task against C, so both sides have the guard on and a blocked task that ends early can't look faster.

| Run | Setup | Tasks | Median per task | Change against C, median of pairs |
|---|---|---:|---:|---:|
| `main-benign` | A | 57 | 22.1 s |  |
| `main-benign` | C | 57 | 22.4 s |  |
| `main-benign` | D | 57 | 18.2 s | -22% |
| `main-benign` | E | 57 | 20.6 s | -6% |
| `open-benign` | A | 57 | 7.9 s |  |
| `open-benign` | C | 57 | 8.4 s |  |
| `open-benign` | D | 57 | 6.3 s | -26% |
| `open-benign` | E | 57 | 5.7 s | -15% |
