"""Why input tokens weren't served from the provider's cache. Reads live traces only. No spend.

    python -m prestige.eval.cache_report --names main-benign,open-benign,open-affinity --md docs/live/cache.md

The trace keeps each request as ordered segments (tool schemas, system prompt, each message) with a hash
and a length. Comparing a call with the call before it in the same conversation splits its input:

- first call: the conversation's opening request. Anything cached here came from other conversations
  that start the same way.
- new: content added since the last call. Only another conversation could have cached it.
- changed: content the last call also sent, but changed or moved, so the prefix broke there. The agent
  or gateway can fix this.
- provider miss: an identical prefix the provider didn't serve from cache. Routing and eviction live
  here, and that's the only part `x-session-affinity` can win back.

Lengths are in characters and turned into tokens by each call's own ratio, so the split is an estimate.
Providers also cache in fixed blocks, which shows up as a small provider miss on every call.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path


def calls(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT r.label, k.id, k.seq, k.input_tokens, k.cached_input_tokens FROM calls k JOIN runs r ON r.id = k.run_id"
            " WHERE r.id IN (SELECT max(id) FROM runs GROUP BY label) ORDER BY k.run_id, k.seq"
        ).fetchall()
        segs = defaultdict(list)
        for call_id, h, chars in conn.execute("SELECT call_id, hash, chars FROM segments ORDER BY call_id, idx"):
            segs[call_id].append((h, chars))
    finally:
        conn.close()
    return [(label, seq, inp, cached, segs[call_id]) for label, call_id, seq, inp, cached in rows]


def split(db: Path) -> dict[str, dict[str, float]]:
    """Token counts per setup: input, cached, and the four kinds of uncached input."""
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    prev: dict[str, list[tuple[str, int]]] = {}
    for label, seq, inp, cached, segs in calls(db):
        setup = label.removeprefix("live/").split(".")[1]
        row = out[setup]
        row["input"] += inp
        row["cached"] += cached
        total = sum(c for _, c in segs) or 1
        per_char = inp / total
        before = prev.get(label)
        prev[label] = segs
        if before is None:
            row["first call"] += inp - cached
            continue
        matched = 0
        for a, b in zip(before, segs):
            if a != b:
                break
            matched += a[1]
        changed = sum(c for _, c in before) - matched  # sent last time, not a prefix now
        reusable = matched * per_char
        miss = max(0.0, reusable - cached)
        fresh = max(0.0, inp - cached - miss)  # what's left of the uncached input
        lost = min(fresh, changed * per_char)
        row["provider miss"] += miss
        row["changed"] += lost
        row["new"] += fresh - lost
        row["prefix breaks"] += changed > 0
        row["later calls"] += 1
    return out


def render(roots: list[Path]) -> str:
    kinds = ("first call", "new", "changed", "provider miss")
    lines = [
        "# Why input missed the cache",
        "",
        "From live traces, no spend. Each row splits one setup's uncached input tokens by cause. See",
        "`prestige/eval/cache_report.py` for how. Estimates, since lengths are in characters.",
        "",
        "| Run | Setup | Input tokens | From cache | " + " | ".join(f"Uncached: {k}" for k in kinds) + " | Later calls with a broken prefix |",
        "|---|---|---:|---:|" + "---:|" * (len(kinds) + 1),
    ]
    for root in roots:
        for setup, row in sorted(split(root / "trace.sqlite").items()):
            uncached = row["input"] - row["cached"]
            cells = [f"{100 * row[k] / uncached:.0f}%" if uncached else "0%" for k in kinds]
            broken = f"{int(row['prefix breaks'])} / {int(row['later calls'])}"
            lines.append(f"| `{root.name}` | {setup} | {int(row['input']):,} | {100 * row['cached'] / row['input']:.1f}% | " + " | ".join(cells) + f" | {broken} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.cache_report", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--names", required=True, help="comma-separated run names under runs/live")
    parser.add_argument("--md", help="write here. Default: print")
    args = parser.parse_args(argv)
    report = render([Path("runs/live") / n for n in args.names.split(",")])
    if args.md:
        Path(args.md).write_text(report, encoding="utf-8")
        print(f"report: {args.md}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
