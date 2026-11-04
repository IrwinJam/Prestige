"""Offline replay of AgentDojo's reference solutions through the gateway.

    python -m prestige.eval.replay --suites banking,slack --labels v1,v2
    python -m prestige.eval.replay --render     # rebuild the report from saved outcomes

No model and no spend. A scripted fake model makes the tool calls in the installed benchmark's ground
truth, so no attack text lives here. Every run happens with the guard off, then once per label version.

Scenarios per user task:
    benign    reference solution, no attack. A block here is a false block
    behaves   reference solution with an attack placed
    hijacked  reference solution until the injection shows up in a tool result, then the injection
              task's calls

The fake model spots the injection by comparing tool output against the attack's own text at run time.
That text stays in memory and never reaches the report.

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
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentdojo.attacks.attack_registry import load_attack
from harness.sim import SimulatedAdapter

from prestige.eval.agentdojo import BENCHMARK_VERSION, DEFAULT_ATTACK, build_pipeline, run_pair, run_task, suite
from prestige.gateway import build_server
from prestige.guard import Guard, Labels
from prestige.guard.policy import value_hash
from prestige.guard.provenance import sink_values, text_of

SCENARIOS = ("benign", "behaves", "hijacked")
ATTACK_PREFIX = "attack_"  # call IDs the fake model gives the injection task's calls
Calls = list[tuple[str, dict[str, Any]]]
Event = tuple[str, str, str, str, str]  # action, rule, tool, arg ("-" for R2), source


@dataclass
class Outcome:
    suite: str
    scenario: str
    user_task: str
    injection_task: str | None
    labels: str | None  # label version. None: guard off
    utility: bool
    security: bool | None  # True: the attack worked. None: no attack placed
    events: list[Event] = field(default_factory=list)
    attack_blocked: bool = False  # one of the injection task's calls was blocked

    @property
    def blocked(self) -> list[Event]:
        return [e for e in self.events if e[0] == "blocked"]


def replay(
    suites: Iterable[str],
    root: str | Path = "runs/replay",
    user_tasks: set[str] | None = None,
    injection_tasks: set[str] | None = None,
    versions: Iterable[str] = ("v1", "v2"),
    on_run: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    root = Path(root)
    outcomes: list[Outcome] = []
    configs: list[str | None] = [None, *versions]
    for suite_name in suites:
        s = suite(suite_name)
        env = s.load_and_inject_default_environment({})
        uids = [u for u in s.user_tasks if user_tasks is None or u in user_tasks]
        iids = [i for i in s.injection_tasks if injection_tasks is None or i in injection_tasks]
        attacks = {i: _calls(s.get_injection_task_by_id(i).ground_truth(env)) for i in iids}
        for version in configs:
            script: dict[str, Any] = {"prompt": None, "solve": [], "attack": [], "markers": [], "approved": set()}
            label_version, _, mode = (version or "").partition("+")
            guard = Guard(Labels.load(f"{suite_name}@{label_version}")) if version else None
            approver = (lambda _key, f: f.value_hash in script["approved"]) if mode == "confirm" else None
            server = build_server(SimulatedAdapter(_scripted(script)), chain=[], guard=guard, db=str(root / "trace.sqlite"), port=0, label="replay", approver=approver)
            try:
                for uid in uids:
                    task = s.get_user_task_by_id(uid)
                    solve = _calls(task.ground_truth(env))
                    for scenario, iid in [("benign", None)] + [(sc, i) for i in iids for sc in ("behaves", "hijacked")]:
                        key = ".".join([suite_name, scenario, (version or "off").replace("+", "-"), uid, iid or "none"])
                        pipeline = build_pipeline(server.proxy.url_for(key), "replay-model")
                        hijack = scenario == "hijacked"
                        script.update(
                            prompt=task.PROMPT,
                            approved=reference_hashes(solve),
                            solve=solve,
                            attack=attacks[iid] if hijack else [],
                            markers=markers(_injections(s, pipeline, uid, iid)) if hijack else [],
                        )
                        logdir = root / "logs" / f"{scenario}-{version or 'off'}"
                        if iid is None:
                            utility, security = run_task(pipeline, suite_name, uid, logdir), None
                        else:
                            utility, security = run_pair(pipeline, suite_name, uid, iid, logdir)
                        events, attack_blocked = _events(server, key)
                        outcome = Outcome(suite_name, scenario, uid, iid, version, utility, security, events, attack_blocked)
                        outcomes.append(outcome)
                        if on_run:
                            on_run(outcome)
            finally:
                server.stop()
    return outcomes


def total_runs(suites: Iterable[str], user_tasks: set[str] | None = None, injection_tasks: set[str] | None = None, versions: Iterable[str] = ("v1", "v2")) -> int:
    per_config = 0
    for name in suites:
        s = suite(name)
        u = len([x for x in s.user_tasks if user_tasks is None or x in user_tasks])
        i = len([x for x in s.injection_tasks if injection_tasks is None or x in injection_tasks])
        per_config += u + 2 * u * i
    return per_config * (1 + len(list(versions)))


def reference_hashes(calls: Calls) -> set[str]:
    """Hashes of every value in a task's reference calls. Stands in for a user who knows the task."""
    return {value_hash(v) for _, args in calls for _, v in sink_values(args, "*")}


def markers(texts: Iterable[str]) -> list[str]:
    """Fingerprints of injected text, compared on letters and digits only.

    Benchmark tools format their output as YAML, which wraps long lines and changes quoting, so exact
    text doesn't match. A 60-character slice from inside each injection does.
    """
    out = []
    for text in texts:
        n = _norm(text)
        if n:
            out.append(n[20:80] if len(n) > 100 else n)
    return out


def _injections(s: Any, pipeline: Any, user_task: str, injection_task: str) -> list[str]:
    attack = load_attack(DEFAULT_ATTACK, s, pipeline)
    return [t for t in attack.attack(s.get_user_task_by_id(user_task), s.get_injection_task_by_id(injection_task)).values() if t]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _calls(function_calls: list[Any]) -> Calls:
    return [(c.function, dict(c.args)) for c in function_calls]


def _scripted(script: dict[str, Any]) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """Fake model. Follows the solution, then the attack once a tool result carries an injection marker.

    It only acts in the conversation that starts with the script's prompt. The step comes from counting
    assistant turns before and after the injection showed up, so it holds no state.
    """
    ids = itertools.count()

    def respond(protocol: str, request: dict[str, Any]) -> dict[str, Any]:
        messages = request.get("messages", [])
        user = next((m for m in messages if m.get("role") == "user"), {})
        if text_of(user.get("content")) != script["prompt"]:
            return _done()
        solved = attacked = 0
        hijacked = False
        for m in messages:
            if m.get("role") == "assistant":
                attacked, solved = (attacked + 1, solved) if hijacked else (attacked, solved + 1)
            elif m.get("role") == "tool" and not hijacked:
                seen = _norm(text_of(m.get("content")))
                hijacked = any(marker in seen for marker in script["markers"])
        if hijacked:
            return _call(f"{ATTACK_PREFIX}{next(ids)}", script["attack"], attacked)
        return _call(f"call_{next(ids)}", script["solve"], solved)

    return respond


def _call(call_id: str, calls: Calls, step: int) -> dict[str, Any]:
    if step >= len(calls):
        return _done()
    name, args = calls[step]
    call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args, default=str)}}
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [call]}, "finish_reason": "tool_calls"}]}


def _done() -> dict[str, Any]:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "Done."}, "finish_reason": "stop"}]}


def _events(server: Any, key: str) -> tuple[list[Event], bool]:
    with server.store.lock:
        rows = server.store.connection.execute(
            "SELECT e.action, e.rule, e.tool, coalesce(e.arg, '-'), e.source, coalesce(e.call_id, '')"
            # Latest run with this key only. A rerun into the same database would count events twice.
            " FROM guard_events e WHERE e.run_id = (SELECT max(id) FROM runs WHERE label = ?) ORDER BY e.id",
            (f"replay/{key}",),
        ).fetchall()
    events = [tuple(r[:5]) for r in rows]
    attack_blocked = any(r[0] == "blocked" and r[5].startswith(ATTACK_PREFIX) for r in rows)
    return events, attack_blocked


# ---- report ----


def render(outcomes: list[Outcome], when: str) -> str:
    """Markdown with counts and identifiers. Nothing from tool output."""
    suites = list(dict.fromkeys(o.suite for o in outcomes))
    versions = sorted({o.labels for o in outcomes if o.labels})
    lines = [
        "# Replay results",
        "",
        f"Generated {when} by `python -m prestige.eval.replay`. AgentDojo {_version()}, benchmark",
        f"{BENCHMARK_VERSION}, attack `important_instructions_no_model_name`. The guard blocks on R1 and",
        "flags R2. `+confirm` adds a stand-in user who approves values from the reference solution.",
        "",
        "Labels v1 were committed before any replay or guard run, though a smoke test had shown one banking",
        "injection task by then. v2 untrusts `get_channels` output. v3 trusts whole listed fields.",
        "",
        "**Replay, not a model.** A scripted fake model makes AgentDojo's reference tool calls. These",
        "numbers describe the guard's rules on those paths. Live results come from a real model. Nothing",
        "is sampled, so there are no intervals.",
        "",
        "| Scenario | What the fake agent does |",
        "|---|---|",
        "| benign | Reference solution with no attack. A block here is a false block |",
        "| behaves | Reference solution with an attack placed |",
        "| hijacked | Reference solution until the injection shows up in a tool result, then the injection task's calls |",
        "",
        "AgentDojo's `security` decides whether an attack worked.",
        "",
    ]
    for name in suites:
        lines += _section(f"## {name}", [o for o in outcomes if o.suite == name], versions, detail=True)
    if len(suites) > 1:
        lines += _section("## All suites", outcomes, versions, detail=False)
    return "\n".join(lines).rstrip() + "\n"


def _section(heading: str, outcomes: list[Outcome], versions: list[str], detail: bool) -> list[str]:
    configs: list[str | None] = [None, *versions]

    def pick(scenario: str, version: str | None) -> list[Outcome]:
        return [o for o in outcomes if o.scenario == scenario and o.labels == version]

    def frac(items: list[Outcome], test: Callable[[Outcome], bool]) -> str:
        return f"{sum(1 for o in items if test(o))} / {len(items)}"

    def name(version: str | None) -> str:
        return f"Guard on, labels {version}" if version else "Guard off"

    rows = [
        ("Benign tasks done, no attack", "benign", lambda o: o.utility),
        ("Tasks done with an attack placed", "behaves", lambda o: o.utility),
        ("Attacks that worked on a hijacked agent", "hijacked", lambda o: bool(o.security)),
    ]
    out = [heading, "", "| | " + " | ".join(name(v) for v in configs) + " |", "|---|" + "---:|" * len(configs)]
    for label, scenario, test in rows:
        out.append(f"| {label} | " + " | ".join(frac(pick(scenario, v), test) for v in configs) + " |")
    worked = {(o.suite, o.user_task, o.injection_task) for o in pick("hijacked", None) if o.security}
    never = len(pick("hijacked", None)) - len(worked)
    out.append("")
    if never:
        out += [f"With the guard off, {never} hijack replays never reached the attack. Their reference solution never read the injection.", ""]

    out += [f"Of the {len(worked)} attacks that worked with the guard off:", "", "| | " + " | ".join(name(v) for v in versions) + " |", "|---|" + "---:|" * len(versions)]
    split = {v: Counter(_stop_reason(o) for o in pick("hijacked", v) if (o.suite, o.user_task, o.injection_task) in worked) for v in versions}
    for reason in ("Guard blocked the attack call", "An earlier block ended the task first", "Still worked"):
        out.append(f"| {reason} | " + " | ".join(str(split[v][reason]) for v in versions) + " |")
    out.append("")
    if not detail:
        return out

    for version in versions:
        guarded = [o for o in outcomes if o.labels == version]
        out += [f"### {name(version)}", ""]
        counts = Counter((o.scenario, e[1], f"{e[2]}.{e[3]}", e[4], e[0]) for o in guarded for e in o.events)
        if counts:
            out += ["| Scenario | Rule | Call and argument | Value came from | Action | Times |", "|---|---|---|---|---|---:|"]
            for (scenario, rule, call, source, action), n in sorted(counts.items(), key=lambda kv: (SCENARIOS.index(kv[0][0]), -kv[1])):
                out.append(f"| {scenario} | {rule} | `{call}` | `{source}` | {action} | {n} |")
            out.append("")
        false_blocks = [o for o in pick("benign", version) if o.blocked]
        out += [f"**False blocks** (benign tasks the guard blocked): {len(false_blocks)}", ""]
        for o in false_blocks:
            out.append(f"- `{o.user_task}`: " + ", ".join(sorted({f'`{e[2]}.{e[3]}` from `{e[4]}`' for e in o.blocked})))
        misses = [o for o in pick("hijacked", version) if o.security]
        out += ["", f"**Misses** (attacks that worked with the guard on): {len(misses)}", ""]
        if misses:
            out += ["<details><summary>Pairs</summary>", ""]
            for o in misses:
                fired = ", ".join(sorted({f"{e[0]} {e[1]} `{e[2]}.{e[3]}`" for e in o.events})) or "nothing fired"
                out.append(f"- `{o.user_task}` × `{o.injection_task}`: {fired}")
            out += ["", "</details>"]
        out.append("")
    return out


def _stop_reason(o: Outcome) -> str:
    if o.security:
        return "Still worked"
    return "Guard blocked the attack call" if o.attack_blocked else "An earlier block ended the task first"


def _version() -> str:
    try:
        return importlib.metadata.version("agentdojo")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.replay", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suites", default="banking,slack")
    parser.add_argument("--labels", default="v1,v2", help="label versions to run with the guard on")
    parser.add_argument("--root", default="runs/replay", help="where logs, traces and raw outcomes go. Never committed")
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
    versions = [v.strip() for v in args.labels.split(",") if v.strip()]
    uids = set(args.user_tasks.split(",")) if args.user_tasks else None
    iids = set(args.injection_tasks.split(",")) if args.injection_tasks else None
    root.mkdir(parents=True, exist_ok=True)
    total = total_runs(suites, uids, iids, versions)
    done = itertools.count(1)

    def progress(o: Outcome) -> None:
        n = next(done)
        if n % 50 == 0 or n == total:
            print(f"  {n}/{total} runs", file=sys.stderr, flush=True)

    print(f"replaying {total} runs over {', '.join(suites)}; AgentDojo's console output goes to {root / 'console.log'}", file=sys.stderr)
    # AgentDojo prints every message, tool output included. It goes to a file under runs/.
    with open(root / "console.log", "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        outcomes = replay(suites, root, uids, iids, versions, on_run=progress)

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
