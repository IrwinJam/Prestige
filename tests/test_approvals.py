import io
import sqlite3
import threading
import time

from fixtures import LABELS, MARKER, read_then, reply
from harness.sim import SimulatedAdapter
from harness.trace import TraceStore

from prestige import approvals, buddy
from prestige.approvals import AskInTerminal
from prestige.gateway import GuardedSession
from prestige.guard import Guard


def pays_marker(protocol, request):
    return reply(("c2", "send_money", {"recipient": MARKER, "amount": 10}))


def session(db, approver):
    store = TraceStore(db)
    run_id = store.start_run("t", {})
    return GuardedSession(SimulatedAdapter(pays_marker), guard=Guard(LABELS), approver=approver, key="k", task_id="t", store=store, run_id=run_id), store


def answer_when_asked(db, yes, seen):
    """Stands in for the person at `buddy watch`."""
    conn = approvals.connect(db)
    for _ in range(200):
        rows = approvals.pending(conn)
        if rows:
            seen.extend(rows)
            approvals.answer(conn, rows[0][0], yes)
            return
        time.sleep(0.02)


def run_with_answer(tmp_path, yes):
    db = tmp_path / "t.sqlite"
    s, store = session(db, AskInTerminal(db, timeout=5, poll=0.02))
    seen = []
    t = threading.Thread(target=answer_when_asked, args=(db, yes, seen))
    t.start()
    response = s.call("chat_completions", read_then(f"Due: 10.00 to {MARKER}"))
    t.join()
    return response, store, seen, db


def test_yes_lets_the_call_through(tmp_path):
    response, store, seen, db = run_with_answer(tmp_path, True)
    assert response["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "send_money"
    assert store.connection.execute("SELECT action FROM guard_events").fetchone()[0] == "confirmed"
    assert seen[0][2:6] == ("send_money", "recipient", "read_file", MARKER)  # the person saw the value


def test_no_blocks_and_the_value_is_wiped(tmp_path):
    response, store, seen, db = run_with_answer(tmp_path, False)
    assert response["choices"][0]["message"]["tool_calls"] is None
    assert store.connection.execute("SELECT action FROM guard_events").fetchone()[0] == "blocked"
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status, value FROM approvals").fetchone() == ("no", None)
    dump = "\n".join(str(r) for t in ("approvals", "guard_events") for r in conn.execute(f"SELECT * FROM {t}"))
    assert MARKER.casefold() not in dump.casefold()


def test_no_answer_means_no(tmp_path):
    db = tmp_path / "t.sqlite"
    s, store = session(db, AskInTerminal(db, timeout=0.1, poll=0.02))
    response = s.call("chat_completions", read_then(f"to {MARKER}"))
    assert response["choices"][0]["message"]["tool_calls"] is None
    assert sqlite3.connect(db).execute("SELECT status, value FROM approvals").fetchone() == ("timeout", None)


def test_shown_values_are_short_and_printable():
    assert approvals.shown("a\x1b[2Jb") == "a?[2Jb"
    assert len(approvals.shown("x" * 500)) == approvals.SHOWN


def test_watch_asks_and_writes_the_answer(tmp_path):
    db = tmp_path / "t.sqlite"
    TraceStore(db)
    conn = approvals.connect(db)
    with conn:
        conn.execute("INSERT INTO approvals (created_at, key, rule, tool, arg, source, value) VALUES ('now', 'k', 'R1', 'send_money', 'recipient', 'read_file', 'GB00TEST')")
    polls = []
    out = io.StringIO()
    s = buddy.Sprite(out, animate=False, color=False)
    assert buddy.watch(s, str(db), poll=0, stop=lambda: polls.append(1) or len(polls) > 1, ask=lambda prompt: "y") == 0
    assert "The agent wants to run send_money.recipient" in out.getvalue()
    assert "'GB00TEST'" in out.getvalue()
    assert conn.execute("SELECT status FROM approvals").fetchone()[0] == "yes"


def test_a_late_answer_changes_nothing(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = approvals.connect(db)
    with conn:
        conn.execute("INSERT INTO approvals (created_at, key, rule, tool, source, status) VALUES ('now', 'k', 'R1', 'send_money', 'read_file', 'timeout')")
    assert approvals.answer(conn, 1, True) is False
    assert conn.execute("SELECT status FROM approvals").fetchone()[0] == "timeout"
