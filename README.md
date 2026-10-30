# Prestige

A gateway that sits between an AI agent and the model. It stops the agent from sending money or data
somewhere that only untrusted content asked for, cuts token cost, and measures both on a public
benchmark.

Status: early. Nothing here has run against a live model yet. The plan is in
[docs/BUILD_PLAN.md](docs/BUILD_PLAN.md).

## The cost half already ships

The cost engine is [agent-cost-harness](https://github.com/IrwinJam/agent-cost-harness), installed
here as a pinned dependency. On 40 tau2-bench retail tasks with Muse it cut agent cost 21% (95% CI 17%
to 25%) with `cache_layout`, and about 37% with low reasoning effort added. Its
[results](https://github.com/IrwinJam/agent-cost-harness/blob/main/docs/RESULTS.md) have the method and
the numbers.

Prestige adds a guard on the agent's tool calls and an evaluation on AgentDojo's public attack suite.

## No attack text in this repo

This repo doesn't contain or publish attacks. Attacks come only from
[AgentDojo](https://github.com/ethz-spylab/agentdojo) (MIT), installed from PyPI at a pinned version.
Run logs stay in `runs/`, which is never committed. Results are published as counts only.
`tests/test_public_hygiene.py` checks this before every commit.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"            # Mac or Linux: .venv/bin/python
.venv/Scripts/python -m pip install -e ".[dev,security]"   # adds AgentDojo
.venv/Scripts/python -m pytest
```
