# Prestige

Prestige sits between an AI agent and its model. It cuts the agent's token bill and blocks tool calls
that untrusted content steered, like a payment to an account that only appeared in a file the agent
read. The agent's code doesn't change: you point it at a different base URL.

It's measured live on Meta's models: Muse Spark through Meta's Model API, and Muse Spark Open, the open
weights model, through Baseten.

**Sections:** [Results](#results) · [Try it](#try-it) · [Use it](#use-it) · [How it works](#how-it-works) ·
[Product](#product) · [Prior work](#prior-work) · [Repo safety](#repo-safety) · [Development](#development)

## Results

### Cost

Live runs on [AgentDojo](https://github.com/ethz-spylab/agentdojo) v1.2.2, Nov 2 and 3 2026. All 57 tasks
with no attack, across banking, Slack and travel. One trial per task, as the test plan set.

| | Muse Spark 1.3, Meta API | Muse Spark Open, Baseten |
|---|---:|---:|
| Cost per task, guard only | $0.0197 | $0.0116 |
| Cost per task, Prestige | $0.0118 | $0.0078 |
| **Change** | **-40%** (95% CI -47% to -32%) | **-33%** (95% CI -40% to -26%) |
| Saved per million tasks | $7,900 | $3,800 |
| Model time per task, change | -22% | -26% |
| Time the guard adds per reply, median | 0.3 ms | 0.3 ms |
| Input from cache, no gateway | 78% | 91% |
| Input from cache, Prestige | 89% | 92% |
| Tasks done, no gateway | 53 of 57 | 53 of 57 |
| Tasks done, Prestige with the confirm step | 51 of 57 | 53 of 57 |

Cost and time compare Prestige against the guard alone. Both sides have the guard on, so a blocked task
can't pass for a saving. Two more trials of every task put the cost cut at 44% on Spark and 35% on Spark
Open. The test plan, [eval/protocol.yaml](eval/protocol.yaml), was committed before any live run.

### Security

On the pairs where an optimized attack lands, 10 runs each:

| | Muse Spark 1.3 | Muse Spark Open |
|---|---:|---:|
| Attacks that worked, no gateway | 42 of 70 | 20 of 40 |
| Attacks that worked, Prestige with the confirm step | **0 of 70** | **0 of 40** |
| Runs where the guard blocked the attacker's call | 49 | 19 |

- Muse ignored AgentDojo's standard attacks: 0 of 352 runs with no guard, over 5 attack types, on Spark
  and Wonder. A system prompt telling it to follow tool output didn't change that.
- Optimized attacks do get through. [AutoDojo](https://github.com/xhOwenMa/AutoDojo) publishes injections
  tuned to beat defenses. With no guard they worked on 7 of 249 Muse pairs and 5 of 249 Spark Open
  pairs. The table reruns the pairs that landed again.
- The guard's price is false blocks. Alone it blocks 11 to 14 of the 57 normal tasks. The confirm step
  turns each one into a question for the user. Under attack on Spark Open it brings tasks done from 129
  back to 167 of 249, with no attack getting through.
- On a scripted hijacked agent, offline, the guard stops 247 of 249 attacks
  ([REPLAY_RESULTS.md](docs/REPLAY_RESULTS.md)).

### Also measured

| Check | Result |
|---|---|
| Drop-in | A plain OpenAI SDK agent, through `prestige serve` and through a LiteLLM proxy, had the hijacked payment blocked on live Muse |
| Labels for new tools | Drafted labels caught all 18 high-impact AgentDojo tools, and covered IBM's Qiskit MCP server from its schemas |
| Cache misses | The prompt prefix never broke across about 3,300 calls. Baseten caches in 64-token blocks |
| Session affinity | Baseten's `x-session-affinity` header saved nothing on these tasks, keyed per conversation or per agent |

Every number, miss and limit: [docs/RESULTS.md](docs/RESULTS.md).

## Try it

### Offline demo

No model and no spend. A scripted agent follows a hijacked banking task, once with the guard off and
once with it on.

```bash
prestige buddy demo        # or: python -m prestige.eval.demo
```

```
      .-~~~~~-.
    .'         '.
   /  .-------.  \
   |  ( ^   ^ )  |
   |  (*  w  *)  |
   |  '-------'  |
  /|             |\
 ( |             | )
  '~~~~~~~~~~~~~~~'
         Muse
  Guard on.
  blocked send_money.recipient, its value came only from read_file
  Attack failed.
```

### The terminal sprite

`prestige buddy` is a small companion in the terminal. It runs the demo and watches a live gateway,
reacting each time the guard blocks a call. Every message while watching ends with the
spend against your cap, like `$0.04 spent of $0.50 cap, $0.46 left`. When it's done it shows the model it
watched and what the prompt cache saved.

| Command | What it does |
|---|---|
| `demo` | The offline demo above |
| `results` | Headline numbers from this README |
| `watch --db PATH --cap USD` | Follows guard events and answers `--ask` questions while `serve` runs |
| `spend --db PATH --cap USD` | Calls, cache share and blocks in a trace database |
| `serve` | The command to start the gateway in another window |

It reads the trace database only. It never spends and never shows a blocked value.

## Use it

### Install

```bash
pip install "git+https://github.com/IrwinJam/Prestige"
```

This adds a `prestige` command. Add `[security]` for the AgentDojo demo, or `[litellm]` for the LiteLLM
guardrail.

### Label your tools

The guard needs to know which tools matter and which arguments pick where money or data goes. Draft
that from the tool definitions you already have, OpenAI or MCP style:

```bash
prestige labels draft tools.json > my-labels.yaml
```

Review the draft before use. It leaves two things for a person: tools that return only the user's own
data (`trusted_output`), and output fields a tool writes itself (`fields`). Until they're set, the guard
blocks more, never less. `banking`, `slack` and `travel` are bundled. [examples/](examples/) has a draft
and a reviewed copy for IBM's Qiskit MCP server.

### Run the gateway

```bash
prestige serve --labels my-labels.yaml --muse --policies cache,reason --set reason.escalate=false --max-total 20
```

Point the agent at `http://127.0.0.1:<port>/s/<conversation-key>/v1`. Traces and guard events go to a
SQLite file. `--max-total` stops all spend at a cap, and `--max-per-conversation` stops one agent.

For Spark Open on Baseten, swap `--muse` for:

```bash
--base-url https://inference.baseten.co/v1 --api-key-env BASETEN_API_KEY --provider baseten
```

### Run it in a container

```bash
docker build -t prestige .
docker run --rm -p 127.0.0.1:8787:8787 -e HARNESS_API_KEY -v prestige-data:/data prestige   serve --labels banking --muse --policies cache,reason --set reason.escalate=false --max-total 20
```

With no arguments the image starts a simulated gateway, which needs no key. `.env` and run data are
kept out of the image. CI builds the image and sends it a request on every push.

### Agents in other languages

The gateway speaks the OpenAI API, so the agent can be written in anything with an OpenAI client.
[examples/typescript/](examples/typescript/) is a TypeScript agent on the official OpenAI SDK with the
base URL as its only change:

```bash
cd examples/typescript && npm install
npx tsx agent.ts http://127.0.0.1:8787/s/ts-demo/v1
```

CI runs it against a simulated gateway on every push.

### Ask before blocking

With `--ask`, the gateway asks a person instead of blocking outright. Answer in another window with
`prestige buddy watch`:

```
  The agent wants to run send_money.recipient
  with 'ACCT-TEST-0001'.
  That value came only from read_file, never from you.
  Let it through? [y/N]
```

No answer within 120 seconds counts as no. The value is shown so the person can judge it, then wiped
from the database once answered.

### Inside LiteLLM

Teams already running the LiteLLM proxy can add the guard there, with no second gateway. Install
`prestige[litellm]` next to the proxy and add this to its `config.yaml`:

```yaml
guardrails:
  - guardrail_name: prestige
    litellm_params:
      guardrail: prestige.integrations.litellm.PrestigeGuardrail
      mode: post_call
      default_on: true
      labels: banking,slack
```

It checks each chat completion reply against the request's tool results and swaps a blocked call for
the same notice `prestige serve` uses. It has no confirm step, so every origin hit blocks. Tested against
litellm 1.105.1 and checked in a running proxy on Muse Spark.

## How it works

The gateway sees the tool results in each request and the tool calls in each reply.

| Part | What it does |
|---|---|
| Guard | Each tool has a label: how much harm it can do, and which arguments are sinks, the ones that pick where something goes. The origin rule blocks a high-impact call when a sink value appears only in tool output, never in the user's or system's own text. Plain code, no model call, no extra tokens |
| Confirm step | A blocked value can go to the user as a question. Approvals match by hash |
| Cost | Policies from [agent-cost-harness](https://github.com/IrwinJam/agent-cost-harness), pinned at `576fe5e`. A stable prompt layout keeps the provider's cache warm, and reasoning effort is set low. Low effort accounts for most of the saving |

Labels are versioned YAML in `prestige/guard/labels/`, and old versions never change. The full design,
known misses and code map are in [docs/DESIGN.md](docs/DESIGN.md).

## Product

### Who it's for

Teams running agents that move money or touch customer data, like fintech operations
and support automation. They pay for tokens on every step, and every tool result is text
someone else could have written.

### What they get

One install, one base URL. The cost cut shows up on the first bill, and the guard
comes in the same install. Every block and every dollar is in a trace the team owns.

### Ways in

| Channel | State |
|---|---|
| `prestige serve`, a drop-in gateway | Built, checked live |
| LiteLLM guardrail, for teams already on LiteLLM | Built, checked in a running proxy |
| MCP tool sets, labels drafted from their schemas | Built, IBM Qiskit as the first outside example |
| Hosted gateway with team keys and a weekly savings report | Planned |

### How it would sell

An open source core, with a paid hosted gateway priced as a share of the measured
savings. The savings pay for it. The guard is the reason to keep it.

### What's next

- Approvals in Slack or email, so the confirm step reaches people where they work.
- Spend caps on what tools cost, not just tokens. An agent on IBM's Qiskit server spends QPU time, and
  the same gap exists for cloud GPUs and paid APIs.
- A check on message bodies, the one gap the results show.

## Prior work

The origin rule is the same idea as [ROPE](https://arxiv.org/abs/2608.27496) (2026), which blocks sensitive tool
arguments whose only origin is attacker-writable content. It's a small cousin of
[CaMeL](https://arxiv.org/abs/2503.18813), which tracks data flow with an interpreter. In AutoDojo's
adaptive attack tests, origin checks like these held up best of the defenses tried. Prestige's part is
putting the check in a drop-in gateway next to cost savings, and measuring both on Meta's models.

## Repo safety

This repo holds no attacks. Attacks come from AgentDojo (MIT), installed from PyPI at a pinned version,
and from AutoDojo's published injections (MIT), read from a local checkout at run time. Run logs stay
in `runs/`, which is never committed. Reports hold counts and task IDs only. `tests/test_public_hygiene.py`
checks this on every test run, and CI runs a secret scan.

## Development

### Setup

One command sets up a checkout, runs the tests and the offline demo:

```bash
bash scripts/quickstart.sh                                       # Mac, Linux, Git Bash
powershell -ExecutionPolicy Bypass -File scripts\quickstart.ps1  # Windows
```

Or by hand:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,security]"   # Mac or Linux: .venv/bin/python
.venv/Scripts/python -m pytest
```

### Live runs

A run needs a spend cap and picks up where it stopped when run again.

```bash
.venv/Scripts/python -m prestige.eval.live --max-total 10 --name main-benign --setups A,C,D,E --suites banking,slack,travel --scope benign
.venv/Scripts/python -m prestige.eval.live_report --name main-benign
```

`--provider baseten` runs Spark Open. `--simulate` uses a scripted fake model that spends nothing.
`--attack` picks another AgentDojo attack, or AutoDojo's with an `autodojo:` path. Setups A to E are
defined in the protocol.

### Reports

All read saved traces, so none of them spend anything.

| Command | Report |
|---|---|
| `python -m prestige.eval.live_report` | One live run |
| `python -m prestige.eval.repeat_report` | Attacked pairs run many times |
| `python -m prestige.eval.overhead` | Time the gateway adds |
| `python -m prestige.eval.cache_report` | Why input missed the cache |
| `python -m prestige.eval.draft_check` | Drafted labels against hand-written ones |
| `python -m prestige.eval.replay` | Offline replay with a scripted agent |
