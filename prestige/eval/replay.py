"""Offline replay of AgentDojo's reference solutions through the gateway, guard off and on.

    python -m prestige.eval.replay --suites banking,slack
    python -m prestige.eval.replay --render     # rebuild the report from saved outcomes

No model and no spend. A scripted fake model makes the tool calls in the installed benchmark's ground
truth, so no attack text lives here.

Scenarios per user task:
    benign    reference solution, no attack. A block here is a false block
    behaves   reference solution with an attack placed
    hijacked  calls the user's request justifies, then the injection task's calls

Results describe the rules on reference paths. Live runs measure a model. Nothing is sampled, so there
are no intervals. Each run gets its own gateway URL key. Logs and traces stay in `runs/`. The report
holds counts and identifiers only.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import importlib.metadata
import itertools
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from harness.sim import SimulatedAdapter

from prestige.eval.agentdojo import BENCHMARK_VERSION, build_pipeline, run_pair, run_task, suite
from prestige.gateway import build_server
from prestige.guard import Guard, Labels
from prestige.guard.provenance import Span, found_in, sink_values

SCENARIOS = ("benign", "behaves", "hijacked")
Calls = list[tuple[str, dict[str, Any]]]
Event = tuple[str, str, str, str, str]  # action, rule, tool, arg ("-" for R2), source


@dataclass
class Outcome:
    suite: str
    scenario: str
    user_task: str
    injection_task: str | None
    guard: bool
    utility: bool
    security: bool | None  # True: the attack worked. None: no attack placed
    events: list[Event] = field(default_factory=list)

    @property
    def blocked(self) -> list[Event]:
        return [e for e in self.events if e[0] == "blocked"]


def replay(
    suites: Iterable[str],
    root: str | Path = "runs/replay",
    user_tasks: set[str] | None = None,
    injection_tasks: set[str] | None = None,
    on_run: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    root = Path(root)
    outcomes: list[Outcome] = []
    for suite_name in suites:
        s = suite(suite_name)
        labels = Labels.load(suite_name)
        env = s.load_and_inject_default_environment({})
        uids = [u for u in s.user_tasks if user_tasks is None or u in user_tasks]
        iids = [i for i in s.injection_tasks if injection_tasks is None or i in injection_tasks]
        attacks = {i: _calls(s.get_injection_task_by_id(i).ground_truth(env)) for i in iids}
        for guarded in (False, True):
            script: dict[str, Any] = {"prompt": None, "calls": []}
            guard = Guard(labels) if guarded else None
            server = build_server(SimulatedAdapter(_scripted(script)), chain=[], guard=guard, db=str(root / "trace.sqlite"), port=0, label="replay")
            try:
                for uid in uids:
                    task = s.get_user_task_by_id(uid)
                    solve = _calls(task.ground_truth(env))
                    justified = [c for c in solve if _justified(c, labels, task.PROMPT)]
                    plan: list[tuple[str, str | None, Calls]] = [("benign", None, solve)]
                    for iid in iids:
                        plan += [("behaves", iid, solve), ("hijacked", iid, justified + attacks[iid])]
                    for scenario, iid, calls in plan:
                        key = ".".join([suite_name, scenario, "guard" if guarded else "open", uid, iid or "none"])
                        script.update(prompt=task.PROMPT, calls=calls)
                        pipeline = build_pipeline(server.proxy.url_for(key), "replay-model")
                        logdir = root / "logs" / f"{scenario}-{'guard' if guarded else 'open'}"
                        if iid is None:
                            utility, security = run_task(pipeline, suite_name, uid, logdir), None
                        else:
                            utility, security = run_pair(pipeline, suite_name, uid, iid, logdir)
                        outcome = Outcome(suite_name, scenario, uid, iid, guarded, utility, security, _events(server, key))
                        outcomes.append(outcome)
                        if on_run:
                            on_run(outcome)
            finally:
                server.stop()
    return outcomes


def total_runs(suites: Iterable[str], user_tasks: set[str] | None = None, injection_tasks: set[str] | None = None) -> int:
    n = 0
    for name in suites:
        s = suite(name)
        u = len([x for x in s.user_tasks if user_tasks is None or x in user_tasks])
        i = len([x for x in s.injection_tasks if injection_tasks is None or x in injection_tasks])
        n += 2 * (u + 2 * u * i)
    return n


def _calls(function_calls: list[Any]) -> Calls:
    return [(c.function, dict(c.args)) for c in function_calls]


def _justified(call: tuple[str, dict[str, Any]], labels: Labels, prompt: str) -> bool:
    """Reads, and calls whose targets the user named. A hijacked agent makes these first."""
    name, args = call
    label = labels.get(name)
    if not label.high_impact:
        return True
    values = sink_values(args, label.sinks)
    request = Span(prompt, True, "user", 0)
    return bool(values) and all(found_in(v, request) for _, v in values)


def _scripted(script: dict[str, Any]) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """Fake model. Makes the current script's calls one per turn, then says it's done."""
    ids = itertools.count()

    def respond(protocol: str, request: dict[str, Any]) -> dict[str, Any]:
        messages = request.get("messages", [])
        user = next((m for m in messages if m.get("role") == "user"), {})
        step = sum(1 for m in messages if m.get("role") == "assistant")
        calls = script["calls"]
        if _text(user.get("content")) == script["prompt"] and step < len(calls):
            name, args = calls[step]
            call = {"id": f"call_{next(ids)}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, default=str)}}
            message = {"role": "assistant", "content": None, "tool_calls": [call]}
            return {"choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}]}
        return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "Done."}, "finish_reason": "stop"}]}

    return respond


def _text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def _events(server: Any, key: str) -> list[Event]:
    with server.store.lock:
        rows = server.store.connection.execute(
            "SELECT e.action, e.rule, e.tool, coalesce(e.arg, '-'), e.source FROM guard_events e JOIN runs r ON r.id = e.run_id"
            " WHERE r.label = ? ORDER BY e.id",
            (f"replay/{key}",),
        ).fetchall()
    return [tuple(r) for r in rows]


# ---- report ----


def render(outcomes: list[Outcome], when: str) -> str:
    """Markdown with counts and identifiers. Nothing from tool output."""
    suites = list(dict.fromkeys(o.suite for o in outcomes))
    lines = [
        "# Replay results",
        "",
        f"Generated {when} by `python -m prestige.eval.replay`. AgentDojo {_version()}, benchmark",
        f"{BENCHMARK_VERSION}, attack `important_instructions_no_model_name`. The guard blocks on R1 and",
        "flags R2. Labels live in `prestige/guard/labels/`.",
        "",
        "**Replay, not a model.** A scripted fake model makes AgentDojo's reference tool calls. These",
        "numbers describe the guard's rules on those paths. Live results come from a real model. Nothing",
        "is sampled, so there are no intervals.",
        "",
        "| Scenario | What the fake agent does |",
        "|---|---|",
        "| benign | Reference solution with no attack. A block here is a false block |",
        "| behaves | Reference solution with an attack placed |",
        "| hijacked | Reads and calls the user's request justifies, then the injection task's calls |",
        "",
        "AgentDojo's `security` decides whether an attack worked.",
        "",
    ]
    for name in suites:
        lines += _suite_section(name, [o for o in outcomes if o.suite == name])
    if len(suites) > 1:
        lines += _suite_section("All suites", outcomes, heading="##")
    return "\n".join(lines).rstrip() + "\n"


def _suite_section(name: str, outcomes: list[Outcome], heading: str = "##") -> list[str]:
    def pick(scenario: str, guard: bool) -> list[Outcome]:
        return [o for o in outcomes if o.scenario == scenario and o.guard == guard]

    def frac(items: list[Outcome], test: Callable[[Outcome], bool]) -> str:
        return f"{sum(1 for o in items if test(o))} / {len(items)}"

    def task(o: Outcome) -> str:
        return f"{o.suite}/{o.user_task}" if multi else o.user_task

    multi = len({o.suite for o in outcomes}) > 1
    hijack_off, hijack_on = pick("hijacked", False), pick("hijacked", True)
    worked_off = {(o.suite, o.user_task, o.injection_task) for o in hijack_off if o.security}
    stopped = [o for o in hijack_on if (o.suite, o.user_task, o.injection_task) in worked_off and not o.security]
    misses = [o for o in hijack_on if o.security]
    false_blocks = [o for o in pick("benign", True) if o.blocked]

    out = [
        f"{heading} {name}",
        "",
        "| | Guard off | Guard on |",
        "|---|---:|---:|",
        f"| Benign tasks done, no attack | {frac(pick('benign', False), lambda o: o.utility)} | {frac(pick('benign', True), lambda o: o.utility)} |",
        f"| Tasks done with an attack placed | {frac(pick('behaves', False), lambda o: o.utility)} | {frac(pick('behaves', True), lambda o: o.utility)} |",
        f"| Attacks that worked on a hijacked agent | {frac(hijack_off, lambda o: bool(o.security))} | {frac(hijack_on, lambda o: bool(o.security))} |",
        "",
        f"The guard stopped {len(stopped)} of the {len(worked_off)} attacks that worked with it off.",
        f"{len(hijack_off) - len(worked_off)} hijack replays failed even with the guard off.",
        "",
    ]
    counts = Counter((o.scenario, e[1], f"{e[2]}.{e[3]}", e[4], e[0]) for o in outcomes if o.guard for e in o.events)
    if counts:
        out += ["Guard events, guard on:", "", "| Scenario | Rule | Call and argument | Value came from | Action | Times |", "|---|---|---|---|---|---:|"]
        for (scenario, rule, call, source, action), n in sorted(counts.items(), key=lambda kv: (SCENARIOS.index(kv[0][0]), -kv[1])):
            out.append(f"| {scenario} | {rule} | `{call}` | `{source}` | {action} | {n} |")
        out.append("")
    out += [f"**False blocks** (benign tasks the guard blocked): {len(false_blocks)}", ""]
    for o in false_blocks:
        out.append(f"- `{task(o)}`: " + ", ".join(sorted({f'`{e[2]}.{e[3]}` from `{e[4]}`' for e in o.blocked})))
    out += ["", f"**Misses** (attacks that worked with the guard on): {len(misses)}", ""]
    if misses:
        out += ["<details><summary>Pairs</summary>", ""]
        for o in misses:
            fired = ", ".join(sorted({f"{e[0]} {e[1]} `{e[2]}.{e[3]}`" for e in o.events})) or "nothing fired"
            out.append(f"- `{task(o)}` × `{o.injection_task}`: {fired}")
        out += ["", "</details>"]
    out.append("")
    return out


def _version() -> str:
    try:
        return importlib.metadata.version("agentdojo")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.replay", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suites", default="banking,slack")
    parser.add_argument("--root", default="runs/replay", help="where logs, traces and the raw outcomes go. Never committed")
    parser.add_argument("--md", default="docs/REPLAY_RESULTS.md", help="where the counts-only report goes")
    parser.add_argument("--user-tasks", help="comma-separated user task IDs, to run a subset")
    parser.add_argument("--injection-tasks", help="comma-separated injection task IDs, to run a subset")
    parser.add_argument("--render", action="store_true", help="rebuild the report from saved outcomes without running anything")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if args.render:
        saved = json.loads((root / "outcomes.json").read_text(encoding="utf-8"))
        outcomes = [Outcome(**{**o, "events": [tuple(e) for e in o["events"]]}) for o in saved]
        _write(render(outcomes, dt.date.today().isoformat()), args.md)
        return 0

    suites = [s.strip() for s in args.suites.split(",") if s.strip()]
    uids = set(args.user_tasks.split(",")) if args.user_tasks else None
    iids = set(args.injection_tasks.split(",")) if args.injection_tasks else None
    root.mkdir(parents=True, exist_ok=True)
    total = total_runs(suites, uids, iids)
    done = itertools.count(1)

    def progress(o: Outcome) -> None:
        n = next(done)
        if n % 50 == 0 or n == total:
            print(f"  {n}/{total} runs", file=sys.stderr, flush=True)

    print(f"replaying {total} runs over {', '.join(suites)}; AgentDojo's console output goes to {root / 'console.log'}", file=sys.stderr)
    # AgentDojo prints every message, tool output included. It goes to a file under runs/.
    with open(root / "console.log", "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        outcomes = replay(suites, root, uids, iids, on_run=progress)

    (root / "outcomes.json").write_text(json.dumps([asdict(o) for o in outcomes], indent=1), encoding="utf-8")
    _write(render(outcomes, dt.date.today().isoformat()), args.md)
    print(f"raw outcomes: {root / 'outcomes.json'}")
    return 0


def _write(report: str, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(report, encoding="utf-8")
    print(f"report: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
