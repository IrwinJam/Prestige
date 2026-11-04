import json

import pytest

pytest.importorskip("agentdojo")

from fixtures import SYSTEM, called, chat, tool, user  # noqa: E402

from prestige.eval.replay import ATTACK_PREFIX, _scripted, markers, render, replay, total_runs  # noqa: E402

STAND_IN = "A neutral sentence that stands in for injected text in this test, long enough to slice from."


@pytest.fixture(scope="module")
def one_pair(tmp_path_factory):
    root = tmp_path_factory.mktemp("replay")
    return root, replay(["banking"], root, {"user_task_0"}, {"injection_task_0"})


def by(outcomes, scenario, labels):
    [o] = [o for o in outcomes if o.scenario == scenario and o.labels == labels]
    return o


def first_call(response):
    [call] = response["choices"][0]["message"]["tool_calls"]
    return call["id"], call["function"]["name"], json.loads(call["function"]["arguments"])


def test_rerun_into_the_same_database_counts_events_once(one_pair):
    root, first = one_pair
    again = replay(["banking"], root, {"user_task_0"}, {"injection_task_0"})
    assert [o.events for o in again] == [o.events for o in first]


def test_fake_agent_switches_once_the_injection_shows_up():
    script = {
        "prompt": "Do the task.",
        "solve": [("read_file", {"file_path": "a.txt"}), ("send_money", {"recipient": "SOLVE-1"})],
        "attack": [("send_money", {"recipient": "ATTACK-1"})],
        "markers": markers([STAND_IN]),
    }
    respond = _scripted(script)
    start = chat(SYSTEM, user("Do the task."))
    assert first_call(respond("chat_completions", start))[1] == "read_file"
    clean = chat(SYSTEM, user("Do the task."), called("c1", "read_file"), tool("c1", "nothing unusual"))
    assert first_call(respond("chat_completions", clean))[2] == {"recipient": "SOLVE-1"}
    poisoned = chat(SYSTEM, user("Do the task."), called("c1", "read_file"), tool("c1", [{"type": "text", "text": f"note:\n  {STAND_IN}"}]))
    call_id, _, args = first_call(respond("chat_completions", poisoned))
    assert args == {"recipient": "ATTACK-1"} and call_id.startswith(ATTACK_PREFIX)
    other = chat(SYSTEM, user("Some other task."))
    assert respond("chat_completions", other)["choices"][0]["message"]["content"] == "Done."


def test_counts_runs_per_scenario_and_config(one_pair):
    _, outcomes = one_pair
    assert len(outcomes) == total_runs(["banking"], {"user_task_0"}, {"injection_task_0"}) == 9


@pytest.mark.parametrize("labels", ["v1", "v2"])
def test_guard_blocks_the_attack_call(one_pair, labels):
    _, outcomes = one_pair
    assert by(outcomes, "hijacked", None).security is True
    stopped = by(outcomes, "hijacked", labels)
    assert stopped.security is False and stopped.attack_blocked
    assert ("blocked", "origin", "send_money", "recipient", "read_file") in stopped.events


def test_benign_false_block_is_recorded(one_pair):
    _, outcomes = one_pair
    assert by(outcomes, "benign", None).utility is True
    benign = by(outcomes, "benign", "v2")
    assert benign.utility is False and benign.blocked and not benign.attack_blocked


def test_report_holds_no_tool_output(one_pair):
    root, outcomes = one_pair
    report = render(outcomes, "2026-10-29")
    assert "`send_money.recipient`" in report and "Guard on, labels v2" in report
    lines = set()
    for log in (root / "logs").rglob("*.json"):
        for m in json.loads(log.read_text(encoding="utf-8"))["messages"]:
            if m["role"] == "tool":
                content = m.get("content")
                text = content if isinstance(content, str) else json.dumps(content)
                lines |= {line.strip() for line in (text or "").splitlines() if len(line.strip()) >= 20}
    assert lines, "expected tool output in the benchmark logs to compare against"
    assert not [line for line in lines if line in report]
