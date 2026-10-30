import json

import pytest

pytest.importorskip("agentdojo")

from prestige.eval.replay import render, replay, total_runs  # noqa: E402


@pytest.fixture(scope="module")
def one_pair(tmp_path_factory):
    root = tmp_path_factory.mktemp("replay")
    return root, replay(["banking"], root, {"user_task_0"}, {"injection_task_0"})


def by(outcomes, scenario, guard):
    [o] = [o for o in outcomes if o.scenario == scenario and o.guard == guard]
    return o


def test_counts_runs_per_scenario_and_guard(one_pair):
    _, outcomes = one_pair
    assert len(outcomes) == total_runs(["banking"], {"user_task_0"}, {"injection_task_0"}) == 6


def test_guard_stops_the_hijack(one_pair):
    _, outcomes = one_pair
    assert by(outcomes, "hijacked", False).security is True
    stopped = by(outcomes, "hijacked", True)
    assert stopped.security is False
    assert ("blocked", "R1", "send_money", "recipient", "read_file") in stopped.events


def test_benign_false_block_is_recorded(one_pair):
    _, outcomes = one_pair
    assert by(outcomes, "benign", False).utility is True
    benign = by(outcomes, "benign", True)
    assert benign.utility is False and benign.blocked


def test_report_holds_no_tool_output(one_pair):
    root, outcomes = one_pair
    report = render(outcomes, "2026-10-30")
    assert "`send_money.recipient`" in report
    lines = set()
    for log in (root / "logs").rglob("*.json"):
        for m in json.loads(log.read_text(encoding="utf-8"))["messages"]:
            if m["role"] == "tool":
                content = m.get("content")
                text = content if isinstance(content, str) else json.dumps(content)
                lines |= {line.strip() for line in (text or "").splitlines() if len(line.strip()) >= 20}
    assert lines, "expected tool output in the benchmark logs to compare against"
    leaked = [line for line in lines if line in report]
    assert not leaked
