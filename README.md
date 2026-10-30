# Prestige

A gateway between an AI agent and its model. It stops tool calls that untrusted content steered, and it
cuts token cost. Both are measured on a public benchmark.

Status: early. Nothing has run against a live model yet. See [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md).

## Cost engine

The cost side is [agent-cost-harness](https://github.com/IrwinJam/agent-cost-harness), pinned as a
dependency. On 40 tau2-bench retail tasks with Muse, `cache_layout` cut agent cost 21% (95% CI 17% to
25%). Low reasoning effort on top brought the cut to about 37%. Its
[results](https://github.com/IrwinJam/agent-cost-harness/blob/main/docs/RESULTS.md) have the method.

Prestige adds a guard on tool calls and an evaluation on AgentDojo.

## No attack text

This repo holds no attacks. Attacks come from [AgentDojo](https://github.com/ethz-spylab/agentdojo)
(MIT), installed from PyPI at a pinned version. Run logs stay in `runs/`, which is never committed.
Reports hold counts only. `tests/test_public_hygiene.py` checks this before every commit.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,security]"   # Mac or Linux: .venv/bin/python
.venv/Scripts/python -m pytest
.venv/Scripts/python -m prestige.eval.replay --suites banking --user-tasks user_task_0 --injection-tasks injection_task_0
```

The last line replays one AgentDojo pair offline, with the guard off and on. It spends nothing.
