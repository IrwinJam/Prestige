# Prestige

A gateway between an AI agent and its model. It cuts token cost and blocks tool calls that untrusted
content steered. It runs on Muse Spark through Meta's Model API and on Muse Spark Open, the open weights
model, through Baseten.

## Results

Live runs on [AgentDojo](https://github.com/ethz-spylab/agentdojo) v1.2.2, Nov 2 2026. All 57 tasks
with no attack, across banking, Slack and travel. One trial per task.

| | Muse Spark 1.3, Meta API | Muse Spark Open, Baseten |
|---|---:|---:|
| Cost per task, guard only | $0.0197 | $0.0116 |
| Cost per task, Prestige | $0.0118 | $0.0078 |
| **Change** | **-40%** (95% CI -47% to -32%) | **-33%** (95% CI -40% to -26%) |
| Input from cache, no gateway | 78% | 91% |
| Input from cache, Prestige | 89% | 92% |
| Tasks done, no gateway | 53 of 57 | 53 of 57 |
| Tasks done, Prestige with the confirm step | 51 of 57 | 53 of 57 |

Cost compares Prestige against the guard alone, so both have the guard on and a blocked task can't
look like a saving. The test plan, [eval/protocol.yaml](eval/protocol.yaml), was committed before any
live run.

Security:

- **Muse ignored every attack.** 0 of 103 runs with no guard, over 5 AgentDojo attack types, 2 suites,
  Spark and Wonder. There was nothing for the guard to stop.
- **Spark Open fell once.** 1 of 249 attacked runs with no guard, 0 of 498 with the guard. In one run
  the model went for an attacker's URL and R1 blocked the call.
- **On a scripted hijacked agent** the guard stops 247 of 249 attacks. That's an offline replay, not a
  model. See [docs/REPLAY_RESULTS.md](docs/REPLAY_RESULTS.md).
- **The price is false blocks.** The guard alone blocks 11 to 14 of the 57 normal tasks. The confirm
  step turns each one into a question for the user. Under attack on Spark Open, it brings tasks done
  from 129 back to 167 of 249, with no attack getting through.

Full numbers, misses and limits: [docs/RESULTS.md](docs/RESULTS.md).

## Demo

```bash
.venv/Scripts/python -m prestige.eval.demo
```

```
AgentDojo banking: user_task_0 with injection_task_0 placed. The agent follows the injection.

guard off
  attack worked

guard on, labels v3
  blocked send_money.recipient: R1, value came from the output of read_file
  attack failed
```

Offline, with a scripted agent. No model and no spend.

## Use it

```bash
.venv/Scripts/python -m prestige serve --labels banking --muse --policies cache,reason --set reason.escalate=false --max-total 20
```

Point any OpenAI-compatible agent at `http://127.0.0.1:<port>/s/<conversation-key>/v1`. For Spark Open,
swap `--muse` for `--base-url https://inference.baseten.co/v1 --api-key-env BASETEN_API_KEY --provider baseten`.
Traces and guard events go to a SQLite file.

## How it works

The gateway sees tool results in each request and tool calls in each reply.

- **Guard.** Each tool gets a label: what it can do and which arguments pick where money or data goes.
  Rule R1 blocks a high-impact call when that destination appears only in tool output and never in the
  user's or system's own text. No model calls, no extra tokens.
- **Confirm step.** A blocked value can go to the user as a question instead. Approvals match by hash.
- **Cost.** Policies from [agent-cost-harness](https://github.com/IrwinJam/agent-cost-harness), pinned
  at commit `576fe5e`: a stable prompt layout so the provider's cache hits more often, and low reasoning
  effort.

Labels are versioned YAML in `prestige/guard/labels/`. Old versions never change.

## No attack text

This repo holds no attacks. Attacks come from AgentDojo (MIT), installed from PyPI at a pinned version.
Run logs stay in `runs/`, which is never committed. Reports hold counts and task IDs only.
`tests/test_public_hygiene.py` checks this before every commit.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,security]"   # Mac or Linux: .venv/bin/python
.venv/Scripts/python -m pytest
.venv/Scripts/python -m prestige.eval.demo
```

## Live runs

A run needs a spend cap and picks up where it stopped when you run it again.

```bash
.venv/Scripts/python -m prestige.eval.live --max-total 10 --name main-benign --setups A,C,D,E --suites banking,slack,travel --scope benign
.venv/Scripts/python -m prestige.eval.live_report --name main-benign
```

Add `--provider baseten` for Spark Open, `--simulate` for a scripted fake model that spends nothing, and
`--attack` to pick another AgentDojo attack. Setups A to E are defined in the protocol.
