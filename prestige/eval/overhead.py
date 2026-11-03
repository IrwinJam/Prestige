"""How much time the gateway adds. Reads live traces only. No model calls, no spend.

    python -m prestige.eval.overhead --names main-benign,open-benign --md docs/live/overhead.md

Guard time: every recorded model call is screened again by the guard, timed on this machine. That's
the work the gateway does per reply, the request copy included. Model time comes from the provider
latency the trace recorded, summed per task, and compared between setups on the same tasks.
"""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import statistics
import time
from collections import defaultdict
from pathlib import Path

from prestige.guard import Guard, Labels

LABELS = "v3"


def guard_times(db: Path) -> list[float]:
    """Seconds the guard takes on each recorded call."""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT r.label, c.protocol, c.request_json, c.response_json FROM calls c JOIN runs r ON r.id = c.run_id"
            " WHERE r.id IN (SELECT max(id) FROM runs GROUP BY label)"
        ).fetchall()
    finally:
        conn.close()
    guards: dict[str, Guard] = {}
    out = []
    for label, protocol, request, response in rows:
        name = label.removeprefix("live/").split(".")[0]
        guard = guards.setdefault(name, Guard(Labels.load(f"{name}@{LABELS}")))
        req, resp = json.loads(request), json.loads(response)
        start = time.perf_counter()
        guard.screen(protocol, copy.deepcopy(req), resp)
        out.append(time.perf_counter() - start)
    return out


def model_time(db: Path) -> dict[str, dict[str, float]]:
    """Provider seconds per task, by setup. Keys are `suite.user_task`."""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT r.label, sum(c.latency_s) FROM calls c JOIN runs r ON r.id = c.run_id"
            " WHERE r.id IN (SELECT max(id) FROM runs GROUP BY label) GROUP BY r.label"
        ).fetchall()
    finally:
        conn.close()
    by_setup: dict[str, dict[str, float]] = defaultdict(dict)
    for label, seconds in rows:
        s, setup, user_task, injection = label.removeprefix("live/").split(".")
        if injection == "none":
            by_setup[setup][f"{s}.{user_task}"] = seconds
    return by_setup


def ms(seconds: float) -> str:
    return f"{1000 * seconds:.2f} ms"


def pct(values: list[float], q: float) -> float:
    return sorted(values)[min(len(values) - 1, int(q * len(values)))]


def render(roots: list[Path]) -> str:
    lines = ["# Time added by the gateway", "", "Live traces, re-screened on one laptop. Counts only.", ""]
    lines += ["## Guard time per model reply", "", "| Run | Replies | Median | 95th percentile | Max | Median model reply |", "|---|---:|---:|---:|---:|---:|"]
    totals = {}
    for root in roots:
        db = root / "trace.sqlite"
        times = guard_times(db)
        conn = sqlite3.connect(db)
        model = [r[0] for r in conn.execute("SELECT latency_s FROM calls WHERE run_id IN (SELECT max(id) FROM runs GROUP BY label)")]
        conn.close()
        lines.append(f"| `{root.name}` | {len(times)} | {ms(statistics.median(times))} | {ms(pct(times, 0.95))} | {ms(max(times))} | {statistics.median(model):.2f} s |")
        totals[root.name] = model_time(db)
    lines += ["", "## Model time per task, no attack", "", "Sum of provider latency over a task's calls. Paired by task against C, so both sides have the guard on and a blocked task that ends early can't look faster.", ""]
    lines += ["| Run | Setup | Tasks | Median per task | Change against C, median of pairs |", "|---|---|---:|---:|---:|"]
    for name, by_setup in totals.items():
        base = by_setup.get("C", {})
        for setup in sorted(by_setup):
            tasks = by_setup[setup]
            change = "" if setup in ("A", "C") else f"{100 * statistics.median(tasks[k] / base[k] - 1 for k in tasks if base.get(k)):+.0f}%"
            lines.append(f"| `{name}` | {setup} | {len(tasks)} | {statistics.median(tasks.values()):.1f} s | {change} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.overhead", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
