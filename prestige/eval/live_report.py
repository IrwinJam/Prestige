"""Report for a live run. Counts and task IDs only.

    python -m prestige.eval.live_report --name main --md docs/SECURITY_RESULTS.md

Rules for each number are in `eval/protocol.yaml`. Attacks that still worked come first.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from prestige.eval.live import read_outcomes

BOOTSTRAPS = 2000


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, mid - half), min(1.0, mid + half)


def paired_interval(diffs: list[float], seed: int = 0) -> tuple[float, float, float]:
    """Mean difference and a 95% bootstrap interval, resampling pairs."""
    if not diffs:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(BOOTSTRAPS))
    return sum(diffs) / len(diffs), means[int(0.025 * BOOTSTRAPS)], means[int(0.975 * BOOTSTRAPS)]


def cost_change(base: dict[Any, float], other: dict[Any, float], seed: int = 0) -> tuple[float, float, float] | None:
    """Percent change in total cost over shared keys, with a 95% bootstrap interval, resampling keys."""
    keys = sorted(set(base) & set(other), key=str)
    if not keys or not sum(base[k] for k in keys):
        return None

    def change(sample: list[Any]) -> float:
        total = sum(base[k] for k in sample)
        return 100 * (sum(other[k] for k in sample) / total - 1) if total else 0.0

    rng = random.Random(seed)
    values = sorted(change(rng.choices(keys, k=len(keys))) for _ in range(BOOTSTRAPS))
    return change(keys), values[int(0.025 * BOOTSTRAPS)], values[int(0.975 * BOOTSTRAPS)]


def load_costs(db: Path) -> dict[str, dict[str, float]]:
    """Per conversation key: cost, tokens, cached tokens, calls."""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT r.label, sum(c.cost_uncached_input + c.cost_cached_input + c.cost_output), sum(c.input_tokens), sum(c.cached_input_tokens), sum(c.reasoning_tokens), count(*)"
            " FROM calls c JOIN runs r ON r.id = c.run_id GROUP BY r.label"
        ).fetchall()
    finally:
        conn.close()
    out = {}
    for label, cost, tokens, cached, reasoning, calls in rows:
        out[label.removeprefix("live/")] = {"cost": cost, "tokens": tokens, "cached": cached, "reasoning": reasoning, "calls": calls}
    return out


def load_events(db: Path) -> dict[str, list[tuple[str, str]]]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT r.label, e.action, e.rule FROM guard_events e JOIN runs r ON r.id = e.run_id").fetchall()
    finally:
        conn.close()
    out: dict[str, list[tuple[str, str]]] = {}
    for label, action, rule in rows:
        out.setdefault(label.removeprefix("live/"), []).append((action, rule))
    return out


def key_of(o: dict[str, Any]) -> str:
    return ".".join([o["suite"], o["setup"], o["user_task"], o["injection_task"] or "none"])


def pair_of(o: dict[str, Any]) -> tuple[str, str, str | None]:
    return o["suite"], o["user_task"], o["injection_task"]


def latest(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The last clean result per run. A rerun after an error replaces the error."""
    best: dict[str, dict[str, Any]] = {}
    for o in outcomes:
        key = key_of(o)
        if not o["error"] or key not in best:
            best[key] = o
    return list(best.values())


def render(outcomes: list[dict[str, Any]], costs: dict[str, dict[str, float]], events: dict[str, list[tuple[str, str]]], manifest: dict[str, Any], baseline: str = "A", headline: str = "D", cost_base: str = "C") -> str:
    clean = [o for o in latest(outcomes) if not o["error"]]
    errors = [o for o in latest(outcomes) if o["error"]]
    setups = [s for s in manifest["setups"] if any(o["setup"] == s for o in clean)]
    pick: Callable[[str, bool], list[dict[str, Any]]] = lambda s, attacked: [o for o in clean if o["setup"] == s and bool(o["injection_task"]) == attacked]

    def frac(items: list[dict[str, Any]], field: str) -> str:
        k, n = sum(1 for o in items if o[field]), len(items)
        if not n:
            return "not run"
        low, high = wilson(k, n)
        return f"{k} / {n} ({100 * k / n:.0f}%, CI {100 * low:.0f} to {100 * high:.0f})"

    def spend(items: list[dict[str, Any]]) -> list[dict[str, float]]:
        return [costs[key_of(o)] for o in items if key_of(o) in costs]

    def per_run(items: list[dict[str, Any]]) -> str:
        rows = spend(items)
        return f"${sum(r['cost'] for r in rows) / len(rows):.4f}" if rows else "not run"

    def cache(items: list[dict[str, Any]]) -> str:
        rows = spend(items)
        tokens = sum(r["tokens"] for r in rows)
        return f"{100 * sum(r['cached'] for r in rows) / tokens:.1f}%" if tokens else "not run"

    lines = [
        "# Live results",
        "",
        f"Model `{manifest['model']}` via {manifest['provider']}. Protocol fingerprint `{manifest['protocol']}`. Suites: {', '.join(manifest['suites'])}. One trial per run.",
        "",
    ]
    if manifest["provider"] == "simulated":
        lines += ["**Simulated.** A scripted fake model made these calls. They check the runner and say nothing about any model.", ""]

    misses = [o for o in pick(headline, True) if o["security"]]
    lines += [f"## Attacks that still worked under setup {headline}: {len(misses)}", ""]
    lines += [f"- `{o['suite']}` `{o['user_task']}` x `{o['injection_task']}`" for o in sorted(misses, key=pair_of)] or ["None."]
    lines += [""]

    lines += ["## By setup", "", "| | " + " | ".join(setups) + " |", "|---|" + "---:|" * len(setups)]
    rows: list[tuple[str, Callable[[str], str]]] = [
        ("Attacks that worked", lambda s: frac(pick(s, True), "security")),
        ("Tasks done, no attack", lambda s: frac(pick(s, False), "utility")),
        ("Tasks done, attack placed", lambda s: frac(pick(s, True), "utility")),
        ("Cost per task, no attack", lambda s: per_run(pick(s, False))),
        ("Input from cache, no attack", lambda s: cache(pick(s, False))),
        ("Tasks with a false block", lambda s: str(sum(1 for o in pick(s, False) if ("blocked", "R1") in events.get(key_of(o), [])))),
        ("Tasks that asked the user", lambda s: str(sum(1 for o in pick(s, False) if ("confirmed", "R1") in events.get(key_of(o), [])))),
    ]
    for name, cell in rows:
        lines.append(f"| {name} | " + " | ".join(cell(s) for s in setups) + " |")
    lines.append("")

    def by_pair(setup: str, attacked: bool, field: str) -> dict[Any, float]:
        return {pair_of(o): float(bool(o[field])) for o in pick(setup, attacked)}

    def by_cost(setup: str) -> dict[Any, float]:
        return {pair_of(o): costs[key_of(o)]["cost"] for o in pick(setup, False) if key_of(o) in costs}

    lines += ["## Comparisons", ""]
    for other in [s for s in setups if s != baseline]:
        base, then = by_pair(baseline, True, "security"), by_pair(other, True, "security")
        shared = sorted(set(base) & set(then), key=str)
        if shared:
            mean, low, high = paired_interval([100 * (then[k] - base[k]) for k in shared])
            lines.append(f"- Attack success, {other} against {baseline}: {mean:+.1f} points (95% CI {low:+.1f} to {high:+.1f}), {len(shared)} pairs.")
        base, then = by_pair(baseline, False, "utility"), by_pair(other, False, "utility")
        shared = sorted(set(base) & set(then), key=str)
        if shared:
            mean, low, high = paired_interval([100 * (then[k] - base[k]) for k in shared])
            lines.append(f"- Tasks done with no attack, {other} against {baseline}: {mean:+.1f} points (95% CI {low:+.1f} to {high:+.1f}), {len(shared)} tasks.")
    change = cost_change(by_cost(cost_base), by_cost(headline))
    if change:
        lines.append(f"- Cost per task with no attack, {headline} against {cost_base}: {change[0]:+.1f}% (95% CI {change[1]:+.1f}% to {change[2]:+.1f}%). Both have the guard on, so blocked tasks don't count as savings.")
    lines.append("")

    total = sum(r["cost"] for r in costs.values())
    fired = Counter(e for o in clean for e in events.get(key_of(o), []))
    lines += [f"Runs: {len(clean)}. Errors left out: {len(errors)}. Spent: ${total:.2f}, at list prices not yet checked against a bill."]
    if fired:
        lines += ["", "Guard events: " + ", ".join(f"{action} {rule} x{n}" for (action, rule), n in sorted(fired.items())) + "."]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.live_report", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="smoke")
    parser.add_argument("--md", help="write here. Default: print")
    args = parser.parse_args(argv)
    root = Path("runs/live") / args.name
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    db = root / "trace.sqlite"
    report = render(read_outcomes(root / "outcomes.jsonl"), load_costs(db), load_events(db), manifest)
    if args.md:
        Path(args.md).write_text(report, encoding="utf-8")
        print(f"report: {args.md}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
