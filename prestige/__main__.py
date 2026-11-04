"""Run the gateway as a local OpenAI-compatible server.

    python -m prestige serve --labels banking,slack --muse --policies cache,reason --max-total 20

The cost harness's `serve` plus the guard. Point an agent at
`http://127.0.0.1:<port>/s/<conversation-key>/v1`. Traces and guard events go to `--db`. Cost report:
`python -m harness profile --db <db> --list`.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from pathlib import Path

from harness.adapters.base import Adapter
from harness.budget import SpendLimit
from harness.serve import ServeError, _describe, _simulated_reply, parse_policies

from prestige.approvals import AskInTerminal
from prestige.gateway import build_server
from prestige.guard import Guard, Labels
from prestige.guard.labels import LabelError


def load_env(path: str | Path = ".env") -> None:
    """Read KEY=VALUE lines into the environment. Anything already set wins."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() and not name.startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip("'\""))


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m prestige",description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the gateway")
    serve.add_argument("--labels", default="", help="comma-separated label files or bundled names, like banking,slack. Required unless --no-guard")
    serve.add_argument("--block", default="R1", help="rules that block a call (comma-separated: R1, R2). Default R1")
    serve.add_argument("--flag", default="R2", help="rules that only log (comma-separated). Default R2")
    serve.add_argument("--no-guard", action="store_true", help="run without the guard, for a baseline")
    serve.add_argument("--policies", default="", help="cost policies, as in the harness: cache, handles, mask, reason. Default none")
    serve.add_argument("--set", action="append", default=[], metavar="POLICY.FIELD=VALUE", help="cost policy setting, e.g. reason.escalate=false")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--db", default="runs/prestige.sqlite", help="trace database")
    serve.add_argument("--budget", type=float, help="cap for this server run only, in USD")
    serve.add_argument("--max-total", type=float, help="cap on everything ever spent in this --db, in USD")
    serve.add_argument("--max-per-day", type=float, help="cap on what's spent since midnight, in USD")
    serve.add_argument("--max-per-conversation", type=float, help="cap on one conversation key, in USD")
    serve.add_argument("--base-url", help="your provider's OpenAI-compatible base URL")
    serve.add_argument("--api-key-env", default="HARNESS_API_KEY", help="env var that holds your provider key")
    serve.add_argument("--provider", default="example", help="provider name to look up in the harness's prices.yaml")
    serve.add_argument("--muse", action="store_true", help="use Meta's Model API for Muse")
    serve.add_argument("--simulate", action="store_true", help="answer with the offline simulator instead of a real provider")
    serve.add_argument("--session-affinity", action="store_true", help="send x-session-affinity per conversation, for more cache hits on Baseten")
    serve.add_argument("--ask", action="store_true", help="ask a person in `prestige buddy watch` before blocking a call")
    serve.add_argument("--ask-timeout", type=float, default=120.0, help="seconds to wait for an answer. No answer means no")
    labels = sub.add_parser("labels", help="draft labels for your own tools: prestige labels draft tools.json")
    labels.add_argument("words", nargs=argparse.REMAINDER, help="draft TOOLS.json")
    buddy = sub.add_parser("buddy", help="a sprite in the terminal that runs the demo and watches the guard")
    buddy.add_argument("words", nargs=argparse.REMAINDER, help="one command to run, like demo or watch. None: interactive")
    args = parser.parse_args(argv)
    if args.command == "labels":
        from prestige.guard import draft

        if args.words[:1] != ["draft"]:
            print("usage: prestige labels draft TOOLS.json", file=sys.stderr)
            return 2
        return draft.main(args.words[1:])
    if args.command == "buddy":
        from prestige import buddy as sprite

        return sprite.main(args.words)

    try:
        chain = parse_policies(args.policies, args.set)
        guard = None
        if not args.no_guard:
            names = [n for n in args.labels.split(",") if n.strip()]
            if not names:
                raise ServeError("--labels is required unless you use --no-guard")
            guard = Guard(Labels.load(*(n.strip() for n in names)), block=_rules(args.block), flag=_rules(args.flag))
        limit = SpendLimit(args.max_total, args.max_per_day, args.max_per_conversation)
        adapter = _adapter(args)
    except (ServeError, LabelError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    approver = AskInTerminal(args.db, args.ask_timeout) if args.ask and guard else None
    server = build_server(adapter, chain=chain, guard=guard, db=args.db, port=args.port, budget_usd=args.budget, limit=limit, host=os.environ.get("HARNESS_HOST", "127.0.0.1"), approver=approver, affinity=args.session_affinity)
    policies = ", ".join(n for n, _ in chain) or "none"
    guard_desc = f"block {sorted(guard.block) or 'nothing'}, flag {sorted(guard.flag) or 'nothing'}" if guard else "off"
    if approver:
        guard_desc += f", ask in `prestige buddy watch --db {args.db}` first"
    print(f"prestige serving on {server.proxy.base_url}  (guard: {guard_desc}; cost policies: {policies}{'; SIMULATED' if args.simulate else ''})")
    print(f"  OpenAI base URL per conversation: {server.proxy.base_url}/s/<key>/v1")
    print(f"  limits: {_describe(limit, args.budget)}")
    print(f"  traces and guard events: {args.db}")
    print("  Ctrl+C to stop", flush=True)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.wait(0.5):
            pass
    finally:
        server.stop()
        print("stopped")
    return 0


def _rules(spec: str) -> list[str]:
    return [r.strip().upper() for r in spec.split(",") if r.strip()]


def _adapter(args: argparse.Namespace) -> Adapter:
    if args.simulate:
        from harness.sim import SimulatedAdapter

        return SimulatedAdapter(_simulated_reply)
    if args.muse:
        from harness.adapters import MuseAdapter

        return MuseAdapter(args.base_url or "https://api.meta.ai/v1", api_key_env=args.api_key_env)
    if not args.base_url:
        raise ServeError("--base-url is required unless you use --muse or --simulate")
    from harness.adapters import OpenAICompatAdapter

    return OpenAICompatAdapter(args.base_url, api_key_env=args.api_key_env, provider=args.provider)


if __name__ == "__main__":
    raise SystemExit(main())
