# Why input missed the cache

From live traces, no spend. Each row splits one setup's uncached input tokens by cause. See
`prestige/eval/cache_report.py` for how. Estimates, since lengths are in characters.

| Run | Setup | Input tokens | From cache | Uncached: first call | Uncached: new | Uncached: changed | Uncached: provider miss | Later calls with a broken prefix |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `main-benign` | A | 1,046,602 | 78.2% | 29% | 23% | 0% | 48% | 0 / 243 |
| `main-benign` | C | 943,579 | 83.5% | 20% | 28% | 0% | 53% | 0 / 205 |
| `main-benign` | D | 866,789 | 89.0% | 16% | 46% | 0% | 38% | 0 / 198 |
| `main-benign` | E | 939,111 | 90.2% | 11% | 51% | 0% | 38% | 0 / 226 |
| `main-benign-t2` | A | 1,052,766 | 76.0% | 20% | 21% | 0% | 59% | 0 / 243 |
| `main-benign-t2` | C | 1,035,013 | 79.5% | 23% | 25% | 0% | 52% | 0 / 229 |
| `main-benign-t2` | D | 922,762 | 91.1% | 16% | 55% | 0% | 29% | 0 / 208 |
| `main-benign-t2` | E | 967,704 | 92.0% | 8% | 61% | 0% | 31% | 0 / 229 |
| `open-benign` | A | 852,350 | 90.7% | 16% | 51% | 0% | 33% | 0 / 195 |
| `open-benign` | C | 822,323 | 91.7% | 16% | 54% | 0% | 30% | 0 / 181 |
| `open-benign` | D | 755,411 | 92.4% | 20% | 50% | 0% | 30% | 0 / 160 |
| `open-benign` | E | 828,839 | 92.4% | 13% | 48% | 0% | 39% | 0 / 184 |
| `open-benign-t2` | A | 934,739 | 94.8% | 13% | 57% | 0% | 30% | 0 / 217 |
| `open-benign-t2` | C | 866,840 | 94.9% | 12% | 60% | 0% | 29% | 0 / 190 |
| `open-benign-t2` | D | 753,520 | 94.8% | 17% | 57% | 0% | 26% | 0 / 161 |
| `open-benign-t2` | E | 810,820 | 95.4% | 13% | 61% | 0% | 26% | 0 / 182 |
| `open-affinity` | D | 728,545 | 89.1% | 37% | 38% | 0% | 24% | 0 / 151 |
