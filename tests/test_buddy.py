import io
import sqlite3
from pathlib import Path

import pytest
from harness.trace import TraceStore

from prestige import buddy
from prestige.gateway import ensure_schema

README = Path(__file__).resolve().parent.parent / "README.md"


def sprite() -> tuple[buddy.Sprite, io.StringIO]:
    out = io.StringIO()
    return buddy.Sprite(out, animate=False, color=False), out


def trace_db(path: Path) -> Path:
    ensure_schema(TraceStore(path))
    return path


def add_event(db: Path, action: str = "blocked") -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO guard_events (run_id, created_at, rule, action, tool, arg, value_hash, value_len, source, source_index)"
        " VALUES ('r1', '2026-11-03T00:00:00', 'R1', ?, 'send_money', 'recipient', 'abc', 10, 'read_file', 2)",
        (action,),
    )
    conn.commit()
    conn.close()


def test_bubble_fits_the_text():
    s, out = sprite()
    rows = s.say("idle", "one\nlonger line")
    lines = out.getvalue().splitlines()
    assert rows == len(lines) == 4
    assert "| longer line |" in lines[2]


def test_results_reads_the_readme_table():
    s, out = sprite()
    assert buddy.results(s, README) == 0
    text = out.getvalue()
    assert "Cost per task, Prestige" in text
    assert "(95% CI" not in text


def test_spend_counts_calls_and_blocks(tmp_path):
    db = trace_db(tmp_path / "t.sqlite")
    add_event(db)
    s, out = sprite()
    assert buddy.spend(s, str(db)) == 0
    assert "0 model calls" in out.getvalue()
    assert "Guard blocks: 1" in out.getvalue()


def test_watch_reacts_to_new_blocks_only(tmp_path):
    db = trace_db(tmp_path / "t.sqlite")
    add_event(db)  # before watch starts, so not shown
    polls = []

    def stop() -> bool:
        polls.append(1)
        if len(polls) == 1:
            add_event(db)
        return len(polls) > 2

    s, out = sprite()
    assert buddy.watch(s, str(db), poll=0, stop=stop) == 0
    text = out.getvalue()
    assert text.count("Blocked send_money.recipient") == 1
    assert "from read_file" in text
    assert "abc" not in text


def test_unknown_command_shows_help():
    s, out = sprite()
    assert buddy.run(s, ["nope"]) == 2
    assert "commands" in out.getvalue()
    assert buddy.run(s, ["quit"]) is None


def test_demo_blocks_the_attack(tmp_path, monkeypatch):
    pytest.importorskip("agentdojo")
    monkeypatch.chdir(tmp_path)
    s, out = sprite()
    assert buddy.demo(s) == 0
    text = out.getvalue()
    assert "Guard off. Attack worked." in text
    assert "blocked send_money.recipient: R1, from read_file" in text
    assert "Attack failed." in text
