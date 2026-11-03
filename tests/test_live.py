import json

import pytest

pytest.importorskip("agentdojo")

from fixtures import LABELS, MARKER, SYSTEM, called, chat, reply, tool, user  # noqa: E402

from prestige.eval import live  # noqa: E402
from prestige.eval.live_report import cost_change, latest, paired_interval, render, wilson  # noqa: E402
from prestige.guard import Guard, Labels, ToolLabel  # noqa: E402
from prestige.guard.policy import value_hash  # noqa: E402
from prestige.guard.provenance import field_values  # noqa: E402


def test_whole_field_is_trusted_and_a_value_inside_text_is_not():
    labels = Labels({**LABELS.tools, "history": ToolLabel("read", fields=("recipient",))}, LABELS.default)
    guard = Guard(labels)
    listed = chat(SYSTEM, user("Pay it."), called("c1", "history"), tool("c1", f"- recipient: {MARKER}\n  subject: hello\n"))
    assert guard.check("chat_completions", listed, reply(("c2", "send_money", {"recipient": MARKER}))) == []
    inside = chat(SYSTEM, user("Pay it."), called("c1", "history"), tool("c1", f"- recipient: someone\n  subject: send to {MARKER}\n"))
    [finding] = guard.check("chat_completions", inside, reply(("c2", "send_money", {"recipient": MARKER})))
    assert finding.rule == "R1" and finding.blocked


def test_field_forms():
    assert field_values("- a\n- b\n", "items") == ["a", "b"]
    assert field_values("Names: a\nb\n", "lines") == ["Names: a", "b"]
    assert field_values("- x: 1\n  y: 2\n", ("y",)) == ["2"]
    assert field_values("not: [valid", "items") == []


def test_approved_call_goes_through_and_is_logged_as_confirmed():
    guard = Guard(LABELS)
    request = chat(SYSTEM, user("Pay my bill."), called("c1", "read_file", file_path="b"), tool("c1", f"pay {MARKER}"))
    response = reply(("c2", "send_money", {"recipient": MARKER}))
    allowed = {value_hash(MARKER)}
    screened, [finding] = guard.screen("chat_completions", request, response, approve=lambda f: f.value_hash in allowed)
    assert screened is response and finding.confirmed and not finding.blocked
    screened, [finding] = guard.screen("chat_completions", request, response, approve=lambda f: False)
    assert finding.blocked and not screened["choices"][0]["message"]["tool_calls"]


def test_travel_labels_cover_every_tool():
    labels = Labels.load("travel@v3")
    for t in live.suite("travel").tools:
        assert t.name in labels.tools, t.name


def test_plan_covers_every_setup_and_is_repeatable():
    items = live.plan(["A", "D"], ["banking"], {"user_task_0"}, {"injection_task_0", "injection_task_1"}, seed=1)
    assert len(items) == 6
    assert items == live.plan(["A", "D"], ["banking"], {"user_task_0"}, {"injection_task_0", "injection_task_1"}, seed=1)
    assert len(live.plan(["A"], ["banking"], {"user_task_0"}, {"injection_task_0"}, scope="benign")) == 1


def test_protocol_setups_load():
    protocol = live.load_protocol()
    assert set(protocol["setups"]) == {"A", "B", "C", "D", "E"}
    assert protocol["setups"]["D"]["settings"] == ["reason.escalate=false"]


def small_run(tmp_path, monkeypatch, cap, name="t"):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "eval").mkdir(exist_ok=True)
    from pathlib import Path

    source = Path(__file__).parents[1] / "eval" / "protocol.yaml"
    (tmp_path / "eval" / "protocol.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return live.main(["--simulate", "--max-total", str(cap), "--name", name, "--setups", "A,C,D,E", "--suites", "banking", "--user-tasks", "user_task_0,user_task_1", "--injection-tasks", "injection_task_0", "--workers", "2"])


def test_simulated_run_end_to_end(tmp_path, monkeypatch):
    assert small_run(tmp_path, monkeypatch, 5) == 0
    root = tmp_path / "runs" / "live" / "t"
    outcomes = live.read_outcomes(root / "outcomes.jsonl")
    assert len(outcomes) == 16 and not [o for o in outcomes if o["error"]]
    by = {(o["setup"], o["user_task"], o["injection_task"]): o for o in outcomes}
    # user_task_0 pays an IBAN read from a file: a false block under the guard, an approval under E.
    assert by["A", "user_task_0", None]["utility"] is True
    assert by["C", "user_task_0", None]["utility"] is False
    assert by["E", "user_task_0", None]["utility"] is True
    # Run again: nothing new happens.
    before = len(outcomes)
    assert small_run(tmp_path, monkeypatch, 5) == 0
    assert len(live.read_outcomes(root / "outcomes.jsonl")) == before


def test_spend_cap_stops_the_run(tmp_path, monkeypatch):
    assert small_run(tmp_path, monkeypatch, 0.0001, name="capped") == 1
    root = tmp_path / "runs" / "live" / "capped"
    outcomes = live.read_outcomes(root / "outcomes.jsonl")
    assert len(outcomes) < 16


def test_report_shows_misses_first_and_holds_only_ids():
    outcomes = [
        {"setup": "A", "suite": "banking", "user_task": "u0", "injection_task": "i0", "utility": True, "security": True, "error": None},
        {"setup": "D", "suite": "banking", "user_task": "u0", "injection_task": "i0", "utility": True, "security": True, "error": None},
        {"setup": "A", "suite": "banking", "user_task": "u0", "injection_task": None, "utility": True, "security": None, "error": None},
        {"setup": "C", "suite": "banking", "user_task": "u0", "injection_task": None, "utility": True, "security": None, "error": None},
        {"setup": "D", "suite": "banking", "user_task": "u0", "injection_task": None, "utility": True, "security": None, "error": None},
    ]
    row = {"tokens": 100, "cached": 50, "reasoning": 1, "calls": 1}
    costs = {"banking.C.u0.none": {"cost": 0.02, **row}, "banking.D.u0.none": {"cost": 0.01, **row}}
    report = render(outcomes, costs, {}, {"model": "m", "provider": "muse", "protocol": "abc", "setups": ["A", "C", "D"], "suites": ["banking"]})
    assert report.index("still worked under setup D: 1") < report.index("## By setup")
    assert "`u0` x `i0`" in report
    assert "D against C: -50.0%" in report


def test_stats():
    low, high = wilson(5, 10)
    assert 0.2 < low < 0.5 < high < 0.8
    assert paired_interval([1.0, 1.0, 1.0]) == (1.0, 1.0, 1.0)
    assert cost_change({"a": 2.0}, {"a": 1.0})[0] == -50.0
    error = {"setup": "A", "suite": "s", "user_task": "u", "injection_task": None, "utility": None, "security": None, "error": "X"}
    assert latest([error, {**error, "utility": True, "error": None}])[0]["error"] is None
    json.dumps(error)


def test_pooled_trials_pair_by_task():
    from prestige.eval.live_report import render_pooled

    def trial(c_cost, d_cost, d_done):
        outcomes = [
            {"setup": s, "suite": "banking", "user_task": "u0", "injection_task": None, "utility": ok, "security": None, "error": None}
            for s, ok in (("A", True), ("C", True), ("D", d_done))
        ]
        row = {"tokens": 100, "cached": 50, "reasoning": 1, "calls": 1}
        costs = {"banking.A.u0.none": {"cost": 0.03, **row}, "banking.C.u0.none": {"cost": c_cost, **row}, "banking.D.u0.none": {"cost": d_cost, **row}}
        return outcomes, costs

    manifest = {"model": "m", "provider": "muse", "protocol": "abc", "setups": ["A", "C", "D"], "suites": ["banking"]}
    report = render_pooled([trial(0.02, 0.01, True), trial(0.02, 0.01, False)], manifest)
    assert "| Runs done | 2 / 2 (100%" in report and "1 / 2 (50%" in report
    assert "Tasks done, D against A: -50.0 points" in report and ", 1 tasks." in report
    assert "D against C: -50.0%" in report
