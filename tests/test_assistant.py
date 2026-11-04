import io
import sqlite3
from pathlib import Path

import pytest
from harness.trace import TraceStore

from prestige import assistant
from prestige.gateway import ensure_schema

README = Path(__file__).resolve().parent.parent / "README.md"


def sprite() -> tuple[assistant.Sprite, io.StringIO]:
    out = io.StringIO()
    return assistant.Sprite(out, animate=False, color=False), out


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


def test_name_and_text_sit_under_the_face():
    s, out = sprite()
    rows = s.say("idle", "one\nlonger line")
    lines = out.getvalue().splitlines()
    assert rows == len(lines) == 13
    assert lines[9].strip() == "Muse"
    assert lines[-2] == "  longer line"


def test_spend_line_shows_the_cap(tmp_path):
    db = trace_db(tmp_path / "t.sqlite")
    s, out = sprite()
    assert assistant.run(s, ["spend", "--db", str(db), "--cap", "5"]) == 0
    assert "$0.00 spent of $5.00 cap, $5.00 left" in out.getvalue()
    assert assistant.run(s, ["cap", "lots"]) == 2


def test_results_reads_the_readme_table():
    s, out = sprite()
    assert assistant.results(s, README) == 0
    text = out.getvalue()
    assert "Cost per task, Prestige" in text
    assert "(95% CI" not in text


def test_spend_counts_calls_and_blocks(tmp_path):
    db = trace_db(tmp_path / "t.sqlite")
    add_event(db)
    s, out = sprite()
    assert assistant.spend(s, str(db)) == 0
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
    assert assistant.watch(s, str(db), poll=0, stop=stop) == 0
    text = out.getvalue()
    assert text.count("Blocked send_money.recipient") == 1
    assert "from read_file" in text
    assert "abc" not in text


def test_unknown_command_shows_help():
    s, out = sprite()
    assert assistant.run(s, ["nope"]) == 2
    assert "commands" in out.getvalue()
    assert assistant.run(s, ["quit"]) is None


def test_demo_blocks_the_attack(tmp_path, monkeypatch):
    pytest.importorskip("agentdojo")
    monkeypatch.chdir(tmp_path)
    s, out = sprite()
    assert assistant.demo(s) == 0
    text = out.getvalue()
    assert "Guard off. Attack worked." in text
    assert "blocked send_money.recipient, its value came only from read_file" in text
    assert "Attack failed." in text


def test_spend_ends_with_the_cheer_and_the_model(tmp_path):
    db = trace_db(tmp_path / "t.sqlite")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO runs (id, created_at, label) VALUES ('r1', '2026-11-03T00:00:00', 'live/x')"
    )
    conn.execute(
        "INSERT INTO calls (run_id, seq, created_at, provider, protocol, model, latency_s, attempts, input_tokens,"
        " cached_input_tokens, output_tokens, reasoning_tokens, cost_uncached_input, cost_cached_input, cost_output,"
        " price_effective_from, price_input, price_cached_input, price_output, price_verified, request_json, response_json)"
        " VALUES ('r1', 1, 'now', 'meta', 'chat_completions', 'muse-spark-1.3', 1.0, 1, 1000000, 1000000, 0, 0,"
        " 0, 0.15, 0, '2026-07-09', 1.25, 0.15, 4.25, 0, '{}', '{}')"
    )
    conn.commit()
    conn.close()
    s, out = sprite()
    assert assistant.spend(s, str(db)) == 0
    text = out.getvalue()
    assert "muse-spark-1.3" in text
    assert "Saved by the prompt cache: $1.10." in text
    assert "  o     .'         '.     o" in text  # both arms up
