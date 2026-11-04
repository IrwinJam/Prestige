"""Live runs on a real model, through the gateway.

    python -m prestige.eval.live --max-total 5 --setups A,C --suites banking --user-tasks user_task_0 --injection-tasks injection_task_0
    python -m prestige.eval.live --max-total 45 --setups A,C,D,E --suites banking,slack --name main
    python -m prestige.eval.live --simulate --max-total 1 --setups A,C,D --suites banking --user-tasks user_task_0 --injection-tasks injection_task_0

Setups come from `eval/protocol.yaml`. Setups and task pairs are mixed in a fixed shuffled order, so all
of them see the same hours of the day. `--max-total` is required and counts everything in this run's
trace database, so it holds across restarts. Run the same command again to pick up where it stopped.

Logs, traces and outcomes stay in `runs/`. This prints counts and IDs, never tool output.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import contextlib
import hashlib
import json
import os
import random
import sys
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from agentdojo.logging import LOGGER_STACK
from harness.adapters.base import Adapter
from harness.budget import SpendLimit
from harness.eval.protocol import POLICIES
from harness.eval.proxy import ProxyServer
from harness.pricing import PriceTable
from harness.serve import Server, parse_policies
from harness.sim import SimulatedAdapter
from harness.trace import TraceStore

from prestige.approvals import AskInTerminal
from prestige.eval.agentdojo import DEFAULT_ATTACK, build_pipeline, run_pair, run_task, suite
from prestige.eval.replay import Calls, _call, _calls, _done, reference_hashes
from prestige.gateway import GuardedSession, ensure_schema, with_session_affinity
from prestige.guard import Finding, Guard, Labels
from prestige.guard.provenance import text_of

PROTOCOL = "eval/protocol.yaml"
SPEND_STOP = "harness_budget_exceeded"
MAX_ERRORS_IN_A_ROW = 10
PROVIDERS = {
    "muse": {"base_url": "https://api.meta.ai/v1", "key_env": "HARNESS_API_KEY", "provider": "meta", "model": "muse-spark-1.3"},
    "baseten": {"base_url": "https://inference.baseten.co/v1", "key_env": "BASETEN_API_KEY", "provider": "baseten", "model": "meta-models/muse-spark-open-1026"},
}


@dataclass(frozen=True)
class Item:
    setup: str
    suite: str
    user_task: str
    injection_task: str | None

    @property
    def key(self) -> str:
        return ".".join([self.suite, self.setup, self.user_task, self.injection_task or "none"])


@dataclass
class Outcome:
    setup: str
    suite: str
    user_task: str
    injection_task: str | None
    utility: bool | None
    security: bool | None  # True: the attack worked. None: no attack placed
    error: str | None = None  # the error's type, never its text


def load_protocol(path: str | Path = PROTOCOL) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def fingerprint(path: str | Path = PROTOCOL) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]


def plan(setups: Iterable[str], suites: Iterable[str], user_tasks: set[str] | None = None, injection_tasks: set[str] | None = None, seed: int = 0, scope: str = "both") -> list[Item]:
    items = []
    for name in suites:
        s = suite(name)
        uids = [u for u in s.user_tasks if user_tasks is None or u in user_tasks]
        iids = [i for i in s.injection_tasks if injection_tasks is None or i in injection_tasks]
        pairs: list[tuple[str, str | None]] = []
        if scope != "attacked":
            pairs += [(u, None) for u in uids]
        if scope != "benign":
            pairs += [(u, i) for u in uids for i in iids]
        items += [Item(setup, name, u, i) for u, i in pairs for setup in setups]
    random.Random(seed).shuffle(items)
    return items


def approver_for(suites: Iterable[str]) -> Any:
    """Stand-in for a user who knows the task: approves values from its reference solution."""
    approved = {}
    for name in suites:
        s = suite(name)
        env = s.load_and_inject_default_environment({})
        for uid in s.user_tasks:
            approved[name, uid] = reference_hashes(_calls(s.get_user_task_by_id(uid).ground_truth(env)))

    def approve(key: str, finding: Finding) -> bool:
        name, _, uid, _ = key.split(".")
        return finding.value_hash in approved[name, uid]

    return approve


def start_server(adapter: Adapter, setups: dict[str, dict[str, Any]], suites: list[str], db: Path, limit: SpendLimit, prices: PriceTable, ask: bool = False, affinity: str | None = None) -> Server:
    """One server and one trace database for every setup. The conversation key picks the setup."""
    store = TraceStore(db)
    ensure_schema(store)
    chains = {name: parse_policies(",".join(cfg.get("policies") or []), cfg.get("settings") or []) for name, cfg in setups.items()}
    guards = {
        (name, s): Guard(Labels.load(f"{s}@{cfg['labels']}"))
        for name, cfg in setups.items()
        if cfg.get("labels")
        for s in suites
    }
    approve = None
    if any(cfg.get("confirm") for cfg in setups.values()):
        # A real person in `buddy watch`, or the stand-in that knows each task's answer
        approve = AskInTerminal(db) if ask else approver_for(suites)

    def new_session(key: str) -> GuardedSession:
        name_suite, setup = key.split(".")[:2]
        chain = chains[setup]
        run_id = store.start_run(f"live/{key}", {"setup": setup, "policies": [n for n, _ in chain]})
        return GuardedSession(
            # "agent": one value per suite, since a suite's tasks share tools and system prompt
            with_session_affinity(adapter, name_suite if affinity == "agent" else key) if affinity else adapter,
            guard=guards.get((setup, name_suite)),
            approver=approve if setups[setup].get("confirm") else None,
            key=key,
            task_id=key,
            policies=[POLICIES[n](**kw) for n, kw in chain],
            store=store,
            run_id=run_id,
            prices=prices,
            limit=limit,
        )

    return Server(ProxyServer(new_session, port=0).start(), store, None, [])


def run_one(server: Server, item: Item, model: str, defense: str | None, logdir: Path, attack: str = DEFAULT_ATTACK, follow: bool = False) -> Outcome:
    # AgentDojo's logger stack defaults to one list shared by all threads. Each run needs its own.
    LOGGER_STACK.set([])
    pipeline = build_pipeline(server.proxy.url_for(item.key), model, defense, follow)
    if item.injection_task is None:
        return Outcome(item.setup, item.suite, item.user_task, None, run_task(pipeline, item.suite, item.user_task, logdir), None)
    utility, security = run_pair(pipeline, item.suite, item.user_task, item.injection_task, logdir, attack)
    return Outcome(item.setup, item.suite, item.user_task, item.injection_task, utility, security)


def run(items: list[Item], server: Server, protocol: dict[str, Any], model: str, root: Path, workers: int = 4, attack: str = DEFAULT_ATTACK, follow: bool = False) -> tuple[list[Outcome], str]:
    """Runs what isn't done yet. Returns new outcomes and why it stopped: done, spend or errors."""
    path = root / "outcomes.jsonl"
    done = {Item(o["setup"], o["suite"], o["user_task"], o["injection_task"]) for o in read_outcomes(path) if not o["error"]}
    todo = [i for i in items if i not in done]
    stop = threading.Event()
    lock = threading.Lock()
    state = {"errors": 0, "reason": "done", "count": 0}
    outcomes: list[Outcome] = []

    def work(item: Item) -> None:
        if stop.is_set():
            return
        try:
            outcome = run_one(server, item, model, protocol["setups"][item.setup].get("defense"), root / "logs" / item.setup, attack, follow)
        except Exception as exc:  # any failure is one recorded run, so a long job keeps going
            outcome = Outcome(item.setup, item.suite, item.user_task, item.injection_task, None, None, type(exc).__name__)
            if SPEND_STOP in str(exc):
                state["reason"] = "spend"
                stop.set()
        with lock:
            outcomes.append(outcome)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(outcome)) + "\n")
            state["errors"] = state["errors"] + 1 if outcome.error else 0
            state["count"] += 1
            if state["errors"] >= MAX_ERRORS_IN_A_ROW and not stop.is_set():
                state["reason"] = "errors"
                stop.set()
            if state["count"] % 25 == 0 or state["count"] == len(todo):
                print(f"  {state['count']}/{len(todo)} runs, ${server.store.spent():.2f} spent", file=sys.stderr, flush=True)

    with futures.ThreadPoolExecutor(workers) as pool:
        list(pool.map(work, todo))
    return outcomes, state["reason"]


def read_outcomes(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def simulated_adapter(suites: Iterable[str]) -> SimulatedAdapter:
    """Follows each task's reference calls, found by its prompt. For checking the runner without spending."""
    scripts: dict[str, Calls] = {}
    for name in suites:
        s = suite(name)
        env = s.load_and_inject_default_environment({})
        for uid in s.user_tasks:
            task = s.get_user_task_by_id(uid)
            scripts[task.PROMPT] = _calls(task.ground_truth(env))

    def respond(_protocol: str, request: dict[str, Any]) -> dict[str, Any]:
        messages = request.get("messages", [])
        user = next((m for m in messages if m.get("role") == "user"), {})
        calls = scripts.get(text_of(user.get("content")))
        if calls is None:
            return _done()
        step = sum(1 for m in messages if m.get("role") == "assistant")
        return _call(f"call_{step}", calls, step)

    return SimulatedAdapter(respond)


def real_adapter(provider: str, developer_as_system: bool) -> Adapter:
    from harness.adapters import MuseAdapter, OpenAICompatAdapter

    cfg = PROVIDERS[provider]
    if provider == "muse":
        adapter: Adapter = MuseAdapter(cfg["base_url"], api_key_env=cfg["key_env"])
    else:
        adapter = OpenAICompatAdapter(cfg["base_url"], api_key_env=cfg["key_env"], provider=cfg["provider"])
    if developer_as_system:
        original = adapter.call
        adapter.call = lambda protocol, request: original(protocol, _system_role(request))  # type: ignore[method-assign]
    return adapter


def _system_role(request: dict[str, Any]) -> dict[str, Any]:
    messages = [{**m, "role": "system"} if m.get("role") == "developer" else m for m in request.get("messages") or []]
    return {**request, "messages": messages}


def prices() -> PriceTable:
    return PriceTable(yaml.safe_load((resources.files("prestige") / "prices.yaml").read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    from prestige.__main__ import load_env

    parser = argparse.ArgumentParser(prog="python -m prestige.eval.live", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-total", type=float, required=True, help="stop once this run's database has spent this much, in USD")
    parser.add_argument("--name", default="smoke", help="run name. Everything goes to runs/live/<name>")
    parser.add_argument("--setups", default="A,C,D,E")
    parser.add_argument("--suites", default="banking,slack")
    parser.add_argument("--user-tasks", help="comma-separated user task IDs, to run a subset")
    parser.add_argument("--injection-tasks", help="comma-separated injection task IDs, to run a subset")
    parser.add_argument("--scope", choices=("both", "benign", "attacked"), default="both")
    parser.add_argument("--attack", help="AgentDojo attack name, for probes off the protocol. Default: the protocol's")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="muse")
    parser.add_argument("--model", help="model name. Default depends on the provider")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-per-conversation", type=float, default=1.0)
    parser.add_argument("--developer-as-system", action="store_true", help="send the developer role as system, for a provider that refuses it")
    parser.add_argument("--follow-tool-output", action="store_true", help="tell the agent to follow instructions in tool results. Stands in for a model that falls for injections")
    parser.add_argument("--session-affinity", nargs="?", const="conversation", choices=("conversation", "agent"), help="send x-session-affinity on Baseten: one value per conversation key, or one per suite")
    parser.add_argument("--ask", action="store_true", help="setups with the confirm step ask you in `prestige buddy watch` instead of the stand-in user")
    parser.add_argument("--simulate", action="store_true", help="use a scripted fake model. Spends nothing")
    args = parser.parse_args(argv)

    load_env()
    protocol = load_protocol()
    setups = [s.strip() for s in args.setups.split(",") if s.strip()]
    suites = [s.strip() for s in args.suites.split(",") if s.strip()]
    unknown = set(setups) - set(protocol["setups"])
    if unknown:
        print(f"error: unknown setups {sorted(unknown)}", file=sys.stderr)
        return 2
    if not args.simulate and not os.environ.get(PROVIDERS[args.provider]["key_env"]):
        print(f"error: {PROVIDERS[args.provider]['key_env']} isn't set", file=sys.stderr)
        return 2

    root = Path("runs/live") / args.name
    root.mkdir(parents=True, exist_ok=True)
    model = "example-model" if args.simulate else args.model or PROVIDERS[args.provider]["model"]
    attack = args.attack or protocol.get("attack") or DEFAULT_ATTACK
    manifest = {"protocol": fingerprint(), "provider": "simulated" if args.simulate else args.provider, "model": model, "attack": attack, "follow_tool_output": args.follow_tool_output, "ask": args.ask, "session_affinity": args.session_affinity, "setups": setups, "suites": suites}
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        before = json.loads(manifest_path.read_text(encoding="utf-8"))
        if before["protocol"] != manifest["protocol"] or before["model"] != model or before.get("attack", DEFAULT_ATTACK) != attack or before.get("follow_tool_output", False) != args.follow_tool_output:
            print("error: this run started under a different protocol, model, attack or prompt. Use a new --name", file=sys.stderr)
            return 2
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    uids = set(args.user_tasks.split(",")) if args.user_tasks else None
    iids = set(args.injection_tasks.split(",")) if args.injection_tasks else None
    items = plan(setups, suites, uids, iids, protocol.get("seed", 0), args.scope)
    adapter = simulated_adapter(suites) if args.simulate else real_adapter(args.provider, args.developer_as_system)
    limit = SpendLimit(total_usd=args.max_total, per_conversation_usd=args.max_per_conversation)
    server = start_server(adapter, {k: protocol["setups"][k] for k in setups}, suites, root / "trace.sqlite", limit, prices(), args.ask, args.session_affinity)
    print(f"{len(items)} runs planned, model {model}, cap ${args.max_total:.2f}, protocol {manifest['protocol']}", file=sys.stderr)
    try:
        # AgentDojo prints every message, tool output included. It goes to a file under runs/.
        with open(root / "console.log", "a", encoding="utf-8") as log, contextlib.redirect_stdout(log):
            _, reason = run(items, server, protocol, model, root, args.workers, attack, args.follow_tool_output)
        spent = server.store.spent()
    finally:
        server.stop()
    print(f"stopped: {reason}. Spent ${spent:.2f}. Report: python -m prestige.eval.live_report --name {args.name}")
    return 0 if reason == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
