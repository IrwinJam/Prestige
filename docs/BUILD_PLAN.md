# Build plan

Revised Oct 29 2026. For the Meta Global AI Developer Hackathon, startup track. Submission is due Nov 4
by 9 PM ET. I'm aiming for noon that day.

Prestige is a gateway that stops an AI agent from sending money or data where untrusted content told it
to, cuts token cost, and measures both. The working name comes from the three acts of a magic trick:
the pledge, the turn, the prestige.

## Two repos

- **[agent-cost-harness](https://github.com/IrwinJam/agent-cost-harness)** is the cost engine. It's
  public, finished, and has real results. Prestige installs it pinned to commit `576fe5e` and never
  changes it. It's the working example of the product: the cost half already runs on Muse and already
  has numbers.
- **Prestige** (this repo) adds the guard, the AgentDojo evaluation, and the combined report.

Nothing gets pushed until I decide to. The repo goes public at submission.

## Constraints

- **No live API calls before Nov 1.** Everything before that runs offline on the cost harness's
  simulator. That's less of a problem than it sounds, because the guard is deterministic. It can be
  built and tested without a model (see "Offline replay").
- **$200 in credits** from Nov 1.
- **Nothing harmful in the repo** (below).

## Goal

> "On AgentDojo's banking and Slack suites with muse-spark-1.3, the gateway cut attack success from X%
> to Y% (95% CI), benign task success stayed within Z points, and with the cost policies on, cost per
> task dropped N%. Here are the attacks it missed."

Anything that doesn't help make that sentence true waits until after Nov 4.

## Rule zero: nothing harmful goes in this repo

I don't write attacks, and I don't publish attack text.

| Never committed | How it's enforced |
|---|---|
| Attack or injection text of any kind, mine or a benchmark's | Attacks come only from AgentDojo 0.1.35, installed from PyPI. Never vendored or copied |
| Raw transcripts, traces, benchmark logs | `runs/`, `*.sqlite`, `*.jsonl` are ignored. AgentDojo logs go under `runs/` |
| Exact argument values the guard blocked | The trace stores a hash and a length, never the value |
| An automated attacker | Cut. An attack generator is itself an attack tool |
| The old arena's taxonomy and stubs | `hackathon-agent-arena` stays local and is never pushed |
| Keys | `.env` is ignored, and CI runs a secret scan |

`tests/test_public_hygiene.py` checks every file git would commit, tracked or not yet added. It fails on
run data, keys, files over 512 KB, and anything shaped like an AgentDojo log. I checked that it catches
a planted log and a force-added `.jsonl`.

What does get published: the guard's code, the tool-impact labels, tests built from neutral data, and
results as counts only. Scripts print task IDs, tool names and pass or fail, never tool output. The demo
shows task IDs and blocked calls, never injected text.

**Check before every push:** `python -m pytest` and `git status --short` showing nothing under `runs/`.

## Status, Oct 29

Done:

- The repo, MIT license, and a pyproject that pulls in the cost harness from GitHub at the pinned commit.
- The hygiene test and CI (tests on Ubuntu and Windows with Python 3.11 and 3.12, plus a gitleaks scan).
- `prestige/eval/agentdojo.py`, which drives AgentDojo through the gateway.
- `prestige/eval/smoke.py`, an offline end-to-end check: AgentDojo, gateway, trace database and
  profiler, with no model and no spend.

What the smoke test settled:

| Question | Answer |
|---|---|
| Does PyPI `agentdojo==0.1.35` have the `openai-compatible` model? | No, only GitHub `main` does. Its `local` option makes the model write tool calls as text, which changes the agent and hides them from the guard. So Prestige uses AgentDojo as a library and hands its pipeline an OpenAI client pointed at the gateway. Native tool calls and AgentDojo's own defenses stay as published |
| Does Muse accept `temperature=0.0`? | It never gets sent. 0.1.35 sends `temperature or NOT_GIVEN`, and its default 0.0 counts as false |
| Which way does `security` point? | `True` means the attack succeeded. A fake agent replaying the injection task's own tool calls scores `True`, and a well-behaved one scores `False` |
| Which attack? | `important_instructions` refuses unknown model names. The published `important_instructions_no_model_name` variant drops the name, so nothing about Muse gets made up |

Found along the way:

- With an attack on, AgentDojo first runs each injection task as a plain task, to check the model could
  do the attacker's goal at all. That's 9 extra runs for banking and 5 for Slack per setup. It's cheap,
  and it's worth reporting.
- AgentDojo 0.1.35 sends its system prompt with the role `developer`. Whether Muse accepts that is a
  Nov 1 question. If it doesn't, Prestige's gateway maps `developer` to `system` before the request
  leaves. That's a change in Prestige, not in AgentDojo.
- The system prompt and the 11 banking tools are the same on every task, so the cost harness's cache
  policies have a stable prompt start to work with.

## Status: guard done early, Oct 29 evening

Done, and the "done when" holds:

- Tool labels for banking and Slack, committed before any replay (`828af01`).
- `prestige/guard/`: labels, provenance matching, rules R1 and R2, and the blocked-call notice.
- `prestige/gateway.py`: `GuardedSession`, the guarded server, and guard events in the trace database
  (hash and length only). `python -m prestige serve` mirrors the cost harness's `serve`, plus the guard.
- 34 new tests, all from neutral markers. 38 in total, all passing.

The smoke test now replays ground truth for banking `user_task_0` × `injection_task_0`:

| Run | Guard off | Guard on |
|---|---|---|
| Hijacked: reads the poisoned file, then does the injection task's calls | attack succeeds | blocked by R1 on `send_money.recipient`, and the attack fails |
| Benign: no attack, "pay the bill in this file" | task done | false block. The IBAN came from the file |
| Behaves: attack placed, agent follows the user | task done | task done |

What this taught me:

- **Under attack, the injection replaces the text it sits in.** In this pair the bill's real IBAN is
  gone, so the legitimate payment's value appears nowhere and R1 stays quiet. That's the "seen nowhere"
  gap from the known misses, showing up in the benchmark's own design.
- **Rule D isn't a free fix.** The attacker's IBAN sits inside the file the user asked the agent to pay
  from. The legitimate payment and the attack follow the same data flow, so no rule based only on where a
  value came from can tell them apart. D would remove this false block and let this attack through.
  Setup E measures that trade-off. It doesn't remove it. This is the same limit CaMeL describes, and the
  results doc will say so.
- **The live runner needs a unique URL key per pair.** The proxy picks a session by how the conversation
  opens, and every injection pair for the same user task opens the same way. With cost policies on, they
  would share one harness session and its state.

## How the guard works

The gateway sees tool results inside each request and tool calls inside each reply. It never runs tools,
the agent does. So the guard screens each reply before the agent gets it.

```
agent (AgentDojo, or anything OpenAI-compatible)
   |  request: system + user (trusted) + tool results (untrusted)
gateway: cost policies rewrite the request -> Muse
   |  reply: tool calls
guard: is a high-impact call aimed somewhere only untrusted content mentioned?
   |-- no:  reply goes to the agent unchanged
   |-- yes: the call is removed, the reply says why, and a guard event is logged
agent runs only the calls that are left
```

**Trust.** System and user messages are trusted. Tool results are untrusted. A tool can be marked
trusted in the label file if it only returns the user's own settings.

**Tool labels.** A YAML file per suite gives each tool an impact level and its *sink* arguments, which
are the arguments that decide where something goes:

```yaml
send_money:            { impact: boundary, sinks: [recipient] }
send_direct_message:   { impact: boundary, sinks: [recipient] }
update_password:       { impact: state,    sinks: [password] }
get_most_recent_transactions: { impact: read }
```

Labels are written from each tool's own description, before any replay or attack run, and committed
first. Unknown tools default to `state`.

**Rule R1, sink provenance.** For a `boundary` or `state` call, each sink value is normalized (case,
spaces, punctuation in IBANs, emails, URLs). If it shows up in an untrusted span and not in any trusted
span, the call is blocked. Content arguments like a message body aren't checked, because summarizing
tool output into a message is normal work.

**Rule R2, tool named by content.** Flag a high-impact call when an untrusted span names that tool and
the user never did. It's a weaker signal, so it's measured on its own (R1 alone vs R1 plus R2).

**Optional rule D, delegated source.** If the user's message names the source a tool read from, like
"pay the bill in bill-december.txt", then values read from that source count as trusted. This targets the
known false-block case. It's a separate setup, decided before any run.

**Cost of the guard.** No model calls and no tokens. It's matching on data the gateway already has. I'll
report the added latency per call.

**Known misses, said up front.** These will get through, and the report lists them with counts:

- A value the model changes on the way, like a number spelled out, reversed, or split up.
- A destination that also appears in trusted text.
- Harm through content arguments only, like the right recipient with the wrong body.
- Anything that isn't a tool call.

This is a small, deterministic take on data-flow defenses. The bigger version is CaMeL
(arXiv:2503.18813), which I'll cite. The claim is the measurement on a real model at the gateway, with
cost measured in the same run. It isn't a new defense idea.

### Code

Prestige doesn't change the cost harness. It reuses its proxy, adapters, trace store and policies.

| File | What |
|---|---|
| `prestige/gateway.py` | `GuardedSession`, a subclass of the harness `Session`, that runs the guard on each reply after the harness's own `review` step. Plus a server builder on the harness `ProxyServer`, the `developer` role fix if Muse needs it, and a `python -m prestige serve` command |
| `prestige/guard/provenance.py` | Value normalization and matching over trusted and untrusted spans |
| `prestige/guard/labels.py` and `prestige/guard/labels/*.yaml` | Loading tool labels, plus the banking and Slack label files |
| `prestige/guard/policy.py` | R1, R2, optional D, the blocked-call notice, and guard events (hash and length only) |
| `prestige/eval/agentdojo.py` | Done for smoke. Grows a CLI for setups, suites and spend caps |
| `prestige/eval/replay.py` | Offline replay, below |
| `prestige/eval/report.py` | Counts-only report: Wilson intervals, paired comparisons, misses first |
| `eval/protocol.yaml` | The test plan, fingerprinted before the main run, like the cost harness's |
| `tests/` | Neutral fixtures and scripted fake replies only |

Subclassing `Session` leans on its private `_send`. That's acceptable because the dependency is pinned
to one commit. After the hackathon, a small public `screen` hook in the cost harness would be cleaner.

## Offline replay (before Nov 1, no tokens)

Every AgentDojo task ships with its own ground truth: the exact tool calls that solve it. The smoke test
already replays them through the gateway with a scripted fake model. That gives two checks of the guard
on every banking and Slack pair, with no model and no spend:

- **Hijack replay.** The user task's own calls first, which read the poisoned data so the injection
  sits in the tool results, then the injection task's calls. The guard should block, and AgentDojo's
  `security` field should flip from `True` to `False`.
- **Benign replay.** Only the user task's calls. The guard shouldn't block anything, and every block
  here is a false block.

These numbers describe the rules, not a model. They get reported apart from the model results and
labelled as replay. They make development fast, catch label mistakes before money is spent, and give a
demo that works even if the live runs go wrong. Real models take other paths, which is why the live
runs still decide the headline.

## Evaluation (live, from Nov 1)

**Benchmark.** AgentDojo v1.2.2 (MIT, ETH Zurich), `important_instructions_no_model_name`, the
`banking` and `slack` suites. That's 16 × 9 = 144 and 21 × 5 = 105 attacked pairs, 249 in all, plus 37
benign tasks and 14 injection-task checks. `travel` is a held-out check if there's time, with its labels
written blind.

**Setups.** Same pairs, same model, one trial per pair, setups run in turns.

| Setup | Gateway | AgentDojo defense |
|---|---|---|
| A. None | no policies | none |
| B. Prompt baseline | no policies | `spotlighting_with_delimiting` |
| C. Guard | guard (R1) | none |
| D. Prestige | guard (R1), `cache_layout`, `reasoning` at low effort | none |
| E. Optional | guard with R1 + R2 + D | none |

D is the headline. C against A isolates the guard. B shows a common prompt-level defense on the same
pairs.

**Measures.**

- Attack success rate: the mean of AgentDojo's `security` on attacked pairs.
- Benign success: utility on the 37 tasks with no attack.
- Success under attack: utility on the attacked pairs.
- False blocks: guard events on benign runs, by rule.
- Cost per task, priced the same way as the cost results.
- Misses: every attacked pair that succeeded under C or D, by task ID, listed first.

**Stats.** Written into `eval/protocol.yaml` before the main run: Wilson 95% intervals per cell, paired
comparisons on the same pairs, and a 5-point margin on benign success. With 37 tasks at one trial, that
margin may be too tight to pass. The cost run taught me that. The report will say so rather than move
the margin.

## Budget

| Run | Size | Estimate |
|---|---|---|
| Live smoke, Nov 1 | 1 benign banking task, then 1 attacked pair | under $0.20 |
| Pilot | banking, 3 user tasks × 9 injections, setups A and C | $1 to $3 |
| Main | 4 setups × (249 attacked + 37 benign + 14 checks) = 1,200 runs | $15 to $50 |
| Optional | setup E, travel | $5 to $15 |
| Reserve | | at least $100 |

Each run goes through the cost harness's `--max-total` cap on its own database. If the pilot shows more
than $0.05 a run, setup B goes first, then Slack.

**Time is the real limit.** All live runs have to fit into Nov 1 and 2. At about 30 seconds a pair,
one setup over both suites is about 2 hours, or about 1.2 with the suites in parallel. The proxy is
threaded.

## Schedule

| Day | Work | Done when |
|---|---|---|
| Thu Oct 29 | Repo, hygiene test, CI, AgentDojo driver, offline smoke | Done. Three of four smoke questions answered |
| Fri Oct 30 | `GuardedSession` and server builder. Guard R1 and R2. Banking and Slack labels, committed first. Neutral unit tests | Done early on Oct 29. The smoke hijack gets blocked. CI on both OSes still to run once the repo is pushed. Free day: start the replay |
| Sat Oct 31 | Offline replay over all 249 pairs plus benign. Counts-only report. Live-run CLI with caps. Write and fingerprint `eval/protocol.yaml`. Rehearse the demo on replay | Replay report renders. Every false block is explained or its label fixed. Protocol committed. One command per setup is ready to paste |
| Sun Nov 1 | Tokens start. Live smoke (the `developer` role, real tool calls, cost per pair), then the pilot, then main setups A and B | A and B finished by night. Run them overnight if needed |
| Mon Nov 2 | Main setups C and D. E and travel only if there's time | Numbers frozen by evening |
| Tue Nov 3 | `docs/SECURITY_RESULTS.md`, README, real numbers into the pitch, demo recording rehearsal | A stranger can go from clone to report |
| Wed Nov 4 | Record the video in the morning, final hygiene check, make the repo public, submit | Submitted by noon ET |

## Demo, 90 seconds

Same AgentDojo banking task, run twice, in one terminal.

1. **The pledge.** An ordinary task: pay a bill. The agent reads files and transactions. Show the task
   ID, not the injected content.
2. **The turn.** With no guard, the payment goes to a recipient the user never mentioned, and the
   benchmark marks it a breach. With the guard, the log shows
   `blocked send_money.recipient: rule R1, from tool result #3, not in user text`.
3. **The prestige.** The certificate: attack success A vs D, benign success, cost per task from the
   cost harness's profiler, and the misses with counts.

Then 30 seconds on the founder story. The replay version of acts 1 and 2 needs no tokens, so it's the
backup if the live runs slip.

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| Muse rejects the `developer` role | Map it to `system` in Prestige's gateway on Nov 1, and list the change |
| Muse already resists the attack, so baseline success is low | Report it as a finding about Muse. Add AgentDojo's `tool_knowledge` attack. The pitch leans on the zero-token guard, the replay results and cost |
| R1 blocks too many real tasks | Setup E with rule D. Report both. Replay shows this before Nov 1 |
| Live runs are slow or rate-limited | Banking only. Slack goes to "next" |
| Nov 1 and 2 aren't enough time | Drop B first, then E and travel. A, C and D are the minimum |
| Labels look tuned to the benchmark | They're committed before any replay or run, and travel is a blind check |

## Not building before Nov 4

The adaptive attacker, any hand-written attacks, a dashboard, streaming, a hosted version, model
switching between Spark and Wonder, and changes to the cost harness.

## Submission checklist

- [ ] README opens with what Prestige does, the one-sentence result, and a three-command quickstart
- [ ] README links the cost harness as the working cost half, with its results
- [ ] `docs/SECURITY_RESULTS.md` has counts only, misses first, replay and live results kept apart, setup and dates
- [ ] CI green, hygiene test passes, secret scan clean
- [ ] Nothing under `runs/` is tracked, and no transcript or attack text is anywhere in the history
- [ ] Demo video shows no injected text
- [ ] Pitch numbers match the results doc
- [ ] Repo is public, and the licenses are listed: this repo, the cost harness, AgentDojo (MIT)

## References

- AgentDojo: https://github.com/ethz-spylab/agentdojo (arXiv:2406.13352)
- CaMeL, "Defeating Prompt Injections by Design": arXiv:2503.18813
- OWASP Top 10 for LLM Applications, prompt injection
- Cost engine and its results: https://github.com/IrwinJam/agent-cost-harness
