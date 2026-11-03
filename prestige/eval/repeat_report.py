"""Report for attacked pairs run many times. Counts and task IDs only.

    python -m prestige.eval.repeat_report --names "rep-muse-b*,rep-muse-s*" --md docs/live/repeats-muse.md

Each run name is one trial. For each pair it counts attacks that worked under each setup, and runs
where the guard blocked the attacker's own target. A blocked value is matched by hash against the
injection task's reference calls, so this needs no tool output.
"""

from __future__ import annotations

import argparse
import glob
import json
import sqlite3
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path
from typing import Any

from prestige.eval.agentdojo import suite
from prestige.eval.live import read_outcomes
from prestige.eval.live_report import latest, wilson
from prestige.eval.replay import _calls, reference_hashes


@cache
def task_hashes(suite_name: str, task: str) -> frozenset[str]:
    s = suite(suite_name)
    env = s.load_and_inject_default_environment({})
    t = s.get_injection_task_by_id(task) if task.startswith("injection_task") else s.get_user_task_by_id(task)
    return frozenset(reference_hashes(_calls(t.ground_truth(env))))


def caught(db: Path) -> tuple[set[str], set[str]]:
    """Run keys where the guard blocked a value from the attacker's reference calls, and run keys where
    it blocked one from the user's own task."""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT r.label, e.value_hash FROM guard_events e JOIN runs r ON r.id = e.run_id"
            " WHERE e.action = 'blocked' AND r.id IN (SELECT max(id) FROM runs GROUP BY label)"
        ).fetchall()
    finally:
        conn.close()
    attacker, user = set(), set()
    for label, value in rows:
        key = label.removeprefix("live/")
        s, _, u, i = key.split(".")
        if value in task_hashes(s, i):
            attacker.add(key)
        elif value in task_hashes(s, u):
            user.add(key)
    return attacker, user


def render(roots: list[Path]) -> str:
    worked: dict[tuple[str, str, str, str], list[bool]] = defaultdict(list)
    stopped: Counter[tuple[str, str, str, str]] = Counter()
    own: Counter[tuple[str, str, str, str]] = Counter()
    manifest: dict[str, Any] = json.loads((roots[0] / "manifest.json").read_text(encoding="utf-8"))
    for root in roots:
        hits, user_hits = caught(root / "trace.sqlite")
        for o in latest(read_outcomes(root / "outcomes.jsonl")):
            if o["error"] or not o["injection_task"]:
                continue
            pair = (o["setup"], o["suite"], o["user_task"], o["injection_task"])
            worked[pair].append(bool(o["security"]))
            key = ".".join([o["suite"], o["setup"], o["user_task"], o["injection_task"]])
            stopped[pair] += key in hits
            own[pair] += key in user_hits
    setups = sorted({p[0] for p in worked})
    pairs = sorted({p[1:] for p in worked})

    def total(setup: str) -> str:
        runs = [x for p, v in worked.items() if p[0] == setup for x in v]
        k, n = sum(runs), len(runs)
        low, high = wilson(k, n)
        return f"{k} / {n} ({100 * k / n:.0f}%, CI {100 * low:.0f} to {100 * high:.0f})"

    lines = [
        "# Repeated attacked pairs",
        "",
        f"Model `{manifest['model']}` via {manifest['provider']}. Attack `{manifest.get('attack', '').split('variants/')[-1]}`. {len(roots)} run names, one trial each.",
        "",
        "| | " + " | ".join(setups) + " |",
        "|---|" + "---:|" * len(setups),
        "| Attacks that worked | " + " | ".join(total(s) for s in setups) + " |",
        "| Runs where the guard blocked the attacker's target | " + " | ".join(str(sum(n for p, n in stopped.items() if p[0] == s)) for s in setups) + " |",
        "| Runs where the guard blocked the user's own value | " + " | ".join(str(sum(n for p, n in own.items() if p[0] == s)) for s in setups) + " |",
        "",
        "| Pair | " + " | ".join(f"{s} worked" for s in setups) + " | " + " | ".join(f"{s} attacker blocked" for s in setups) + " | " + " | ".join(f"{s} user blocked" for s in setups) + " |",
        "|---|" + "---:|" * (3 * len(setups)),
    ]
    for p in pairs:
        cells = [f"{sum(worked[(s, *p)])} / {len(worked[(s, *p)])}" for s in setups]
        cells += [str(stopped[(s, *p)]) for s in setups]
        cells += [str(own[(s, *p)]) for s in setups]
        lines.append(f"| `{p[0]}` `{p[1]}` × `{p[2]}` | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.repeat_report", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--names", required=True, help="comma-separated run names or globs under runs/live")
    parser.add_argument("--md", help="write here. Default: print")
    args = parser.parse_args(argv)
    roots = sorted({Path(p) for pattern in args.names.split(",") for p in glob.glob(str(Path("runs/live") / pattern))})
    report = render(roots)
    if args.md:
        Path(args.md).write_text(report, encoding="utf-8")
        print(f"report: {args.md}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
