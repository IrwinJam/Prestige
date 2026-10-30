"""Gateway: the cost harness's proxy, with the guard on every reply.

`GuardedSession` checks each reply against what the model could read: the agent's history plus harness
tool results, before masking shortens them. Guard events go into the trace database's `guard_events`
table, next to cost. Each stores a hash and a length, never the value.

It overrides the harness's private `Session._send`. The pinned harness commit keeps that stable.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any

from harness.adapters.base import Adapter
from harness.budget import Budget, SpendLimit
from harness.eval.protocol import POLICIES
from harness.eval.proxy import ProxyServer
from harness.policies import conv
from harness.pricing import PriceTable
from harness.serve import Server
from harness.session import Session
from harness.trace import TraceStore
from harness.usage import Protocol

from prestige.guard import Finding, Guard

SCHEMA = """
CREATE TABLE IF NOT EXISTS guard_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    call_seq INTEGER,
    created_at TEXT NOT NULL,
    rule TEXT NOT NULL,
    action TEXT NOT NULL,
    tool TEXT NOT NULL,
    arg TEXT,
    value_hash TEXT,
    value_len INTEGER,
    source TEXT NOT NULL,
    source_index INTEGER NOT NULL
);
"""


def ensure_schema(store: TraceStore) -> None:
    with store.lock:
        store.connection.executescript(SCHEMA)


class GuardedSession(Session):
    def __init__(self, adapter: Adapter, *, guard: Guard | None = None, **kwargs: Any):
        super().__init__(adapter, **kwargs)
        self.guard = guard
        self.findings: list[Finding] = []
        if self.store is not None:
            ensure_schema(self.store)

    def _send(self, protocol: Protocol, agent_request: dict[str, Any], agent_items: list[dict[str, Any]]) -> dict[str, Any]:
        response = super()._send(protocol, agent_request, agent_items)
        if self.guard is None:
            return response
        seen = copy.deepcopy(agent_request)
        conv.items(protocol, seen)[:] = self._with_injections(agent_items)
        response, findings = self.guard.screen(protocol, seen, response, skip=self.ctx.harness_tools)
        if findings:
            self.findings.extend(findings)
            self._record(findings)
        return response

    def _record(self, findings: list[Finding]) -> None:
        if self.store is None:
            return
        now = dt.datetime.now(dt.UTC).isoformat()
        with self.store.lock:
            db = self.store.connection
            seq = db.execute("SELECT max(seq) FROM calls WHERE run_id = ?", (self.run_id,)).fetchone()[0]
            rows = [
                (self.run_id, seq, now, f.rule, "blocked" if f.blocked else "flagged", f.tool, f.arg, f.value_hash, f.value_len, f.source, f.source_index)
                for f in findings
            ]
            with db:
                db.executemany(
                    "INSERT INTO guard_events (run_id, call_seq, created_at, rule, action, tool, arg, value_hash, value_len, source, source_index)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )


def build_server(
    adapter: Adapter,
    *,
    chain: list[tuple[str, dict[str, Any]]],
    guard: Guard | None,
    db: str = "runs/prestige.sqlite",
    port: int = 8787,
    budget_usd: float | None = None,
    limit: SpendLimit | None = None,
    prices: PriceTable | None = None,
    label: str = "prestige",
    host: str = "127.0.0.1",
) -> Server:
    """The harness's `build_server`, with a guarded session per conversation."""
    store = TraceStore(db)
    ensure_schema(store)
    budget = Budget(budget_usd) if budget_usd else None
    prices = prices or PriceTable.load()
    guard_meta = {"block": sorted(guard.block), "flag": sorted(guard.flag)} if guard else None

    def new_session(key: str) -> GuardedSession:
        policies = [POLICIES[name](**kwargs) for name, kwargs in chain]
        meta = {"serve": True, "key": key, "policies": [n for n, _ in chain], "guard": guard_meta}
        run_id = store.start_run(f"{label}/{key}", meta)
        return GuardedSession(
            adapter, guard=guard, task_id=key, policies=policies, store=store, run_id=run_id, prices=prices, budget=budget, limit=limit
        )

    return Server(ProxyServer(new_session, host=host, port=port).start(), store, budget, chain)
