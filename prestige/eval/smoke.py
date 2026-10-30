"""Offline check that AgentDojo, the gateway and the trace database fit together. Spends nothing.

    python -m prestige.eval.smoke

A scripted fake model stands in for Muse, behind the cost harness's simulator.

- Run 1 behaves: it reads the account balance once and answers.
- Run 2 plays a fully hijacked agent: it makes exactly the tool calls that AgentDojo's own injection
  task checks for, taken from the installed benchmark at run time. That shows which way AgentDojo's
  `security` field points before any real number depends on it.

Prints only task IDs, tool names and pass or fail. Never the injected text.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from typing import Any

from agentdojo.task_suite.load_suites import get_suite
from harness.serve import build_server
from harness.sim import SimulatedAdapter

from prestige.eval.agentdojo import BENCHMARK_VERSION, build_pipeline, run_attacked

SUITE = "banking"
USER_TASK = "user_task_0"
INJECTION_TASK = "injection_task_0"
DB = "runs/smoke/trace.sqlite"


def scripted(prompt: str, calls: list[tuple[str, dict[str, Any]]]) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
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


def hijacked_calls() -> list[tuple[str, dict[str, Any]]]:
    suite = get_suite(BENCHMARK_VERSION, SUITE)
    env = suite.load_and_inject_default_environment({})
    return [(c.function, dict(c.args)) for c in suite.get_injection_task_by_id(INJECTION_TASK).ground_truth(env)]


def run(label: str, calls: list[tuple[str, dict[str, Any]]]) -> tuple[bool, bool]:
    prompt = get_suite(BENCHMARK_VERSION, SUITE).get_user_task_by_id(USER_TASK).PROMPT
    server = build_server(SimulatedAdapter(scripted(prompt, calls)), chain=[], db=DB, port=0, label=f"smoke-{label}")
    try:
        pipeline = build_pipeline(f"{server.proxy.base_url}/v1", "fake-model")
        results = run_attacked(pipeline, SUITE, f"runs/smoke/{label}", user_tasks=[USER_TASK], injection_tasks=[INJECTION_TASK])
    finally:
        server.stop()
    key = (USER_TASK, INJECTION_TASK)
    return results["utility_results"][key], results["security_results"][key]


def main() -> int:
    calls = hijacked_calls()
    print(f"{SUITE} {USER_TASK} x {INJECTION_TASK}, attack loaded from the installed AgentDojo")
    for label, script in (("behaves", [("get_balance", {})]), ("hijacked", calls)):
        utility, security = run(label, script)
        tools = ", ".join(name for name, _ in script)
        print(f"  {label:9} calls [{tools}]  utility={utility}  security={security}")
    print(f"traces: {DB}  ->  python -m harness profile --db {DB} --list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
