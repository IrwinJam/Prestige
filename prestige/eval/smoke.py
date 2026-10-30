"""Offline check that AgentDojo, the gateway, the guard and the trace database fit together. Spends nothing.

    python -m prestige.eval.smoke

A scripted fake model stands in for Muse, behind the cost harness's simulator. It replays tool calls
from the installed benchmark's own ground truth, so no attack text is written here:

- "benign" replays the user task's own solution with no attack placed. A block here is a false block.
- "behaves" replays the same solution with the attack placed. The injection replaces the text the
  solution's values came from, so they appear nowhere the guard can see, and R1 stays quiet.
- "hijacked" makes the user task's read calls, which bring the poisoned data into the conversation, then
  makes exactly the calls AgentDojo's injection task checks for.

Each runs with the guard off and on. Prints only task IDs, tool names, rules and pass or fail, never
tool output.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from typing import Any

from agentdojo.task_suite.load_suites import get_suite
from harness.sim import SimulatedAdapter

from prestige.eval.agentdojo import BENCHMARK_VERSION, build_pipeline, run_attacked, run_benign
from prestige.gateway import build_server
from prestige.guard import Guard, Labels

SUITE = "banking"
USER_TASK = "user_task_0"
INJECTION_TASK = "injection_task_0"
DB = "runs/smoke/trace.sqlite"

Calls = list[tuple[str, dict[str, Any]]]


def scripted(prompt: str, calls: Calls) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """A fake model that makes these tool calls one per turn, then says it's done.

    It follows the script only in the conversation that starts with `prompt`. AgentDojo also runs each
    injection task on its own first, to check the model could do it at all, and those get "Done.".
    The step comes from how many assistant turns the conversation already has, so it holds no state.
    """
    ids = itertools.count()

    def respond(protocol: str, request: dict[str, Any]) -> dict[str, Any]:
        messages = request.get("messages", [])
        user = next((m for m in messages if m.get("role") == "user"), {})
        step = sum(1 for m in messages if m.get("role") == "assistant")
        if _text(user.get("content")) == prompt and step < len(calls):
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


def scripts(labels: Labels) -> dict[str, Calls]:
    suite = get_suite(BENCHMARK_VERSION, SUITE)
    env = suite.load_and_inject_default_environment({})
    solve = [(c.function, dict(c.args)) for c in suite.get_user_task_by_id(USER_TASK).ground_truth(env)]
    attack = [(c.function, dict(c.args)) for c in suite.get_injection_task_by_id(INJECTION_TASK).ground_truth(env)]
    reads = [c for c in solve if not labels.get(c[0]).high_impact]
    return {"benign": solve, "behaves": solve, "hijacked": reads + attack}


def run(label: str, calls: Calls, guard: Guard | None, attacked: bool) -> tuple[bool, bool | None, list[tuple[str, ...]]]:
    prompt = get_suite(BENCHMARK_VERSION, SUITE).get_user_task_by_id(USER_TASK).PROMPT
    server = build_server(SimulatedAdapter(scripted(prompt, calls)), chain=[], guard=guard, db=DB, port=0, label=f"smoke-{label}")
    try:
        pipeline = build_pipeline(f"{server.proxy.base_url}/v1", "fake-model")
        if attacked:
            results = run_attacked(pipeline, SUITE, f"runs/smoke/{label}", user_tasks=[USER_TASK], injection_tasks=[INJECTION_TASK])
        else:
            results = run_benign(pipeline, SUITE, f"runs/smoke/{label}", user_tasks=[USER_TASK])
        with server.store.lock:
            events = server.store.connection.execute(
                "SELECT e.action, e.rule, e.tool, e.arg, e.source FROM guard_events e JOIN runs r ON r.id = e.run_id"
                " WHERE r.label LIKE ? ORDER BY e.id",
                (f"smoke-{label}/%",),
            ).fetchall()
    finally:
        server.stop()
    if not attacked:
        return next(iter(results["utility_results"].values())), None, [tuple(e) for e in events]
    key = (USER_TASK, INJECTION_TASK)
    return results["utility_results"][key], results["security_results"][key], [tuple(e) for e in events]


def main() -> int:
    labels = Labels.load(SUITE)
    print(f"{SUITE} {USER_TASK} x {INJECTION_TASK}, attack loaded from the installed AgentDojo")
    print("security=True means the attack succeeded")
    for name, calls in scripts(labels).items():
        for guarded in (False, True):
            label = f"{name}{'-guard' if guarded else ''}"
            utility, security, events = run(label, calls, Guard(labels) if guarded else None, attacked=name != "benign")
            outcome = f"utility={utility}" + ("  (no attack)" if security is None else f"  security={security}")
            print(f"  {label:15} calls [{', '.join(n for n, _ in calls)}]  {outcome}")
            for action, rule, tool, arg, source in events:
                print(f"      {action} {tool}.{arg or '-'}: {rule}, from the output of {source}")
    print(f"traces: {DB}  ->  python -m harness profile --db {DB} --list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
