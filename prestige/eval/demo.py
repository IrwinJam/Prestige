"""One hijacked AgentDojo task with the guard off, then on. For the demo video.

    python -m prestige.eval.demo
    python -m prestige.eval.demo --user-task user_task_3 --injection-task injection_task_1

Offline: a scripted fake agent follows the task's reference solution until the injection shows up,
then makes the injection task's calls. No model and no spend. Prints task IDs and guard events, never
tool output. Logs go to `runs/demo/`.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from prestige.eval.replay import replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.demo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", default="banking")
    parser.add_argument("--user-task", default="user_task_0")
    parser.add_argument("--injection-task", default="injection_task_0")
    parser.add_argument("--labels", default="v3")
    args = parser.parse_args(argv)

    root = Path("runs/demo")
    root.mkdir(parents=True, exist_ok=True)
    # AgentDojo prints every message, tool output included. It goes to a file under runs/.
    with open(root / "console.log", "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        outcomes = replay([args.suite], root, {args.user_task}, {args.injection_task}, [args.labels])
    print(f"AgentDojo {args.suite}: {args.user_task} with {args.injection_task} placed. The agent follows the injection.\n")
    for o in outcomes:
        if o.scenario != "hijacked":
            continue
        print("guard on, labels " + o.labels if o.labels else "guard off")
        for action, rule, tool, arg, source in o.events:
            print(f"  {action} {tool}.{arg}: the value came only from {source}")
        print(f"  attack {'worked' if o.security else 'failed'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
