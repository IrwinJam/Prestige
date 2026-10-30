import httpx
from fixtures import LABELS, MARKER, read_then, reply
from harness.sim import SimulatedAdapter
from harness.trace import TraceStore

from prestige.gateway import GuardedSession, build_server
from prestige.guard import Guard


def pays_marker(protocol, request):
    return reply(("c2", "send_money", {"recipient": MARKER, "amount": 10}))


def session(tmp_path, guard):
    store = TraceStore(tmp_path / "trace.sqlite")
    return GuardedSession(SimulatedAdapter(pays_marker), guard=guard, task_id="t", store=store, run_id=store.start_run("t", {})), store


def test_blocked_calls_never_reach_the_agent_and_events_are_saved(tmp_path):
    s, store = session(tmp_path, Guard(LABELS))
    response = s.call("chat_completions", read_then(f"Due: 10.00 to {MARKER}"))
    assert response["choices"][0]["message"]["tool_calls"] is None
    rows = store.connection.execute("SELECT call_seq, rule, action, tool, arg, value_len, source FROM guard_events").fetchall()
    assert [tuple(r) for r in rows] == [(0, "R1", "blocked", "send_money", "recipient", len(MARKER), "read_file")]


def test_guard_events_never_hold_the_value(tmp_path):
    s, store = session(tmp_path, Guard(LABELS))
    s.call("chat_completions", read_then(f"to {MARKER}"))
    dump = "\n".join(str(tuple(r)) for r in store.connection.execute("SELECT * FROM guard_events"))
    assert dump and MARKER.casefold() not in dump.casefold()


def test_without_a_guard_the_reply_is_unchanged(tmp_path):
    s, store = session(tmp_path, None)
    response = s.call("chat_completions", read_then(f"to {MARKER}"))
    assert response["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "send_money"
    assert store.connection.execute("SELECT count(*) FROM guard_events").fetchone()[0] == 0


def test_through_the_http_server(tmp_path):
    server = build_server(SimulatedAdapter(pays_marker), chain=[], guard=Guard(LABELS), db=str(tmp_path / "s.sqlite"), port=0)
    try:
        r = httpx.post(f"{server.proxy.url_for('task-1')}/chat/completions", json=read_then(f"to {MARKER}"), timeout=10)
    finally:
        server.stop()
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"].startswith("Blocked send_money")
