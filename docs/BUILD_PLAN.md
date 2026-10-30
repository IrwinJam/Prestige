# Build plan

Updated Oct 30 2026. Meta Global AI Developer Hackathon, startup track. Due Nov 4 at 9 PM ET. Target:
noon that day.

Prestige is a gateway for AI agents. It stops a tool call when untrusted content chose where the call
sends money or data. It also cuts token cost. The name comes from the final act of a magic trick.

## Repos

- **[agent-cost-harness](https://github.com/IrwinJam/agent-cost-harness)** is the cost engine. It's
  public and finished, with results. Prestige pins it to commit `576fe5e` and never edits it.
- **Prestige** holds the guard and the AgentDojo evaluation. It stays private until submission.

## Constraints

- No live API calls before Nov 1. Until then everything runs on the cost harness's simulator. The guard
  needs no model, so it gets built and tested offline.
- $200 in credits from Nov 1.
- No harmful content in the repo. See below.

## Goal

> "On AgentDojo's banking and Slack suites with muse-spark-1.3, the gateway cut attack success from X%
> to Y% (95% CI) and kept benign success within Z points. With cost policies on, cost per task fell N%.
> The attacks it missed are listed."

Work that doesn't serve that sentence waits until after Nov 4.

## Repo safety

No attacks get written here, and no attack text gets published.

| Never committed | Enforced by |
|---|---|
| Attack or injection text | Attacks come only from AgentDojo 0.1.35 on PyPI. Never copied in |
| Transcripts, traces, benchmark logs | `runs/`, `*.sqlite`, `*.jsonl` are ignored. AgentDojo writes under `runs/` |
| Blocked values | Guard events store a hash and a length |
| Automated attackers | Not built |
| The old arena's taxonomy | `hackathon-agent-arena` stays local |
| Keys | `.env` is ignored. CI runs gitleaks |

`tests/test_public_hygiene.py` checks every file git would commit, tracked or not. It fails on run
data, keys, files over 512 KB and benchmark logs. `tests/test_replay.py` checks that no line of tool
output reaches the replay report.

Published: guard code, tool labels, tests built from neutral markers, and counts. Scripts print IDs and
outcomes, never tool output. The demo shows task IDs and blocked calls, never injected text.

Before every push: `python -m pytest` passes and `git status --short` shows nothing under `runs/`.

## Smoke test results

Oct 29. Repo, hygiene test, CI and the AgentDojo driver are done.

| Question | Answer |
|---|---|
| Does PyPI `agentdojo==0.1.35` take an OpenAI-compatible URL? | No. Only GitHub `main` does. Its `local` mode turns tool calls into prompt text, which hides them from the guard. Prestige drives AgentDojo as a library and passes it an OpenAI client aimed at the gateway |
| Does Muse accept `temperature=0.0`? | It's never sent. 0.1.35 sends `temperature or NOT_GIVEN`, and 0.0 is falsy |
| Which way does `security` point? | `True` means the attack worked. A scripted hijack confirmed it |
| Which attack? | `important_instructions_no_model_name`. The default variant rejects model names it doesn't know |

Also found:

- AgentDojo's suite runner first runs each injection task alone. The per-pair runner skips that.
- AgentDojo 0.1.35 sends the system prompt with role `developer`. Muse support for that role is unknown
  until Nov 1. The fallback maps it to `system` in the gateway.
- The system prompt and tool list stay fixed across tasks. The cache policies get a stable prefix.

## Guard build results

Oct 29, a day early.

- Banking and Slack tool labels, committed before any run.
- `prestige/guard/`: label loading, provenance matching, rules R1 and R2, the blocked-call notice.
- `prestige/gateway.py`: `GuardedSession`, the guarded server, guard events in the trace database.
- Tests built from neutral markers. All pass.

Replay of banking `user_task_0` × `injection_task_0`:

| Run | Guard off | Guard on |
|---|---|---|
| Hijacked: reads the poisoned file, then makes the injection task's calls | attack works | R1 blocks `send_money.recipient`. Attack fails |
| Benign: no attack, "pay the bill in this file" | task done | false block. The IBAN came from the file |
| Behaves: attack placed, agent follows the user | task done | task done |

Findings:

- An injection replaces the text it sits in. Under attack the bill's real IBAN disappears, so the
  reference payment uses a value the agent never saw. R1 has nothing to match.
- Rule D trades security for utility. The attacker's IBAN sits in the file the user asked the agent to
  pay from. The real payment and the attack share one data flow, and provenance alone can't separate
  them. CaMeL reports the same limit.
- Pairs that share a user task open the same way, and the proxy would give them one session. The runner
  gives each pair its own URL key.

## Replay run results

Oct 29. 1,605 runs over banking and Slack: guard off, then labels v1, then labels v2. Full counts are
in [REPLAY_RESULTS.md](REPLAY_RESULTS.md).

| All suites | Guard off | Labels v1 | Labels v2 |
|---|---:|---:|---:|
| Benign tasks done | 35 of 37 | 20 of 37 | 16 of 37 |
| Attacks that worked | 249 of 249 | 45 of 249 | 2 of 249 |
| Stopped at the attack call | | 169 | 212 |
| Stopped because an earlier block ended the task | | 35 | 35 |

**First run.** Two problems showed up, both found by checking counts against the run logs:

- The hijack script made only calls the user's request justified, so 24 replays never read the
  injection. It now follows the reference solution until the injection shows up in a tool result. Every
  hijack replay reaches the attack now.
- The v1 labels trusted `get_channels` output, and AgentDojo puts one Slack injection in a channel name.
  Any workspace member can name a channel. v2 untrusts it, in its own commit with the reason. v1 stays
  as committed, for comparison.

**Banking.** v1 and v2 match. The guard blocks all 144 attacks at the attack call. Three benign tasks
get blocked.

**Slack.**

- v2 closes the channel-name hole. Attacks that worked fall from 45 to 2.
- Both remaining attacks send a direct message to a real member with a harmful body. That's the known
  content-argument gap.
- v2 costs four more benign tasks. Each posts to a channel named by `get_channels`.
- 35 attacks stop only because an earlier false block ended the task. AgentDojo counts them as stopped.
  The guard didn't catch them, and the report lists them apart.

**False blocks under v2** fall into two groups:

- Whole fields from a listing: channel names from `get_channels` and a recipient from the transaction
  history. Five tasks. Injected values sit inside free text instead, so field-level provenance can
  separate them. This goes next.
- Values inside text the user pointed at: links in channel messages, an email on a web page, the IBAN
  in a bill. Fourteen tasks. Rule D and a confirm step target these.

## How the guard works

The gateway sees tool results in each request and tool calls in each reply. The agent runs the tools.
So the guard checks each reply before the agent gets it.

```
agent (AgentDojo, or anything OpenAI-compatible)
   |  request: system and user messages (trusted), tool results (untrusted)
gateway: cost policies rewrite the request -> Muse
   |  reply: tool calls
guard: does a high-impact call aim where only untrusted content pointed?
   |-- no:  reply goes to the agent unchanged
   |-- yes: call removed, notice added, event logged
agent runs the calls that are left
```

**Trust.** System and user messages are trusted. Tool output is untrusted unless its label sets
`trusted_output`.

**Labels.** One YAML file per suite gives each tool an impact level. High-impact tools list their
*sink* arguments, the ones that pick where something goes.

```yaml
send_money:            { impact: boundary, sinks: [recipient] }
send_direct_message:   { impact: boundary, sinks: [recipient] }
update_password:       { impact: state,    sinks: [password] }
get_most_recent_transactions: { impact: read }
```

Labels come from tool definitions only. Unlisted tools get every argument checked. Each version lives in
its own folder, `labels/v1/` and `labels/v2/`, and old versions never change.

**R1, sink provenance.** A high-impact call is blocked when a sink value appears in untrusted output and
nowhere in trusted text. Matching ignores case and spacing. URLs match without scheme or `www.`.
Message bodies aren't checked. Summarizing tool output into a message is normal work.

**R2, tool named by content.** Flags a high-impact call when untrusted output names the tool and
trusted text doesn't. It only flags by default.

**Rule D, delegated source.** Optional. Values read from a source the user named count as trusted.
Setup E measures it.

**Cost.** No model calls and no tokens. Latency per call goes in the report.

**Known misses.** Every report lists these with counts.

- Values the model rewrites, like spelled-out or split numbers.
- Destinations that also appear in trusted text.
- Harm through content arguments alone.
- Values the agent never saw, which happens when an injection replaces the original text.
- Anything that isn't a tool call.

**Prior work.** CaMeL (arXiv:2503.18813) tracks data flow with a full interpreter. Prestige is a small
deterministic version at the gateway, measured on a real model with cost in the same run.

### Code

Prestige doesn't edit the cost harness. It reuses its proxy, adapters, trace store and policies.

| File | Role |
|---|---|
| `prestige/gateway.py` | `GuardedSession` subclasses the harness `Session` and screens each reply. Also the server builder and the `developer` role fix when Muse needs it |
| `prestige/__main__.py` | `python -m prestige serve`, the harness's `serve` plus guard options |
| `prestige/guard/provenance.py` | Trusted and untrusted spans, value matching |
| `prestige/guard/labels.py`, `labels/v*/*.yaml` | Versioned tool labels |
| `prestige/guard/policy.py` | R1, R2, the notice, findings |
| `prestige/eval/agentdojo.py` | AgentDojo through the gateway, per pair |
| `prestige/eval/replay.py` | Offline replay, guard off and once per label version, with its report |
| `prestige/eval/report.py` | Live report with Wilson intervals. Not started |
| `eval/protocol.yaml` | Test plan, fingerprinted before the main run. Not started |

`GuardedSession` overrides the harness's private `_send`. The pinned commit keeps that stable. After the
hackathon it should become a public hook in the harness.

## Offline replay

Each AgentDojo task ships reference tool calls. The replay sends them through the gateway with the
guard off and on. No model and no spend.

| Scenario | What the fake agent does |
|---|---|
| benign | Reference solution with no attack. A block here is a false block |
| behaves | Reference solution with an attack placed |
| hijacked | Reads and calls the user's request justifies, then the injection task's calls |

Replay numbers describe the rules, not a model. They're reported apart from live results.

## Live evaluation

From Nov 1. AgentDojo v1.2.2, attack `important_instructions_no_model_name`, suites `banking` and
`slack`. That's 144 plus 105 attacked pairs and 37 benign tasks. `travel` is a blind check with time
left over.

| Setup | Gateway | AgentDojo defense |
|---|---|---|
| A. None | no policies | none |
| B. Prompt baseline | no policies | `spotlighting_with_delimiting` |
| C. Guard | guard (R1) | none |
| D. Prestige | guard (R1), `cache_layout`, `reasoning` at low effort | none |
| E. Optional | guard with R1, R2 and D | none |

D is the headline. C against A isolates the guard. B compares a prompt-level defense on the same pairs.

**Measures.**

- Attack success: mean of AgentDojo's `security` over attacked pairs.
- Benign success: utility on the 37 tasks with no attack.
- Success under attack: utility on attacked pairs.
- False blocks: guard events on benign runs, by rule.
- Cost per task, priced like the cost results.
- Misses: attacked pairs that worked under C or D, by task ID, listed first.

**Stats.** Written into `eval/protocol.yaml` before the main run. Wilson 95% intervals per cell, paired
comparisons on the same pairs, a 5-point margin on benign success. 37 tasks at one trial may be too few
to pass that margin. The report says so rather than moving the margin.

## Budget

| Run | Size | Estimate |
|---|---|---|
| Live smoke, Nov 1 | 1 benign task, 1 attacked pair | under $0.20 |
| Pilot | banking, 3 user tasks × 9 injections, setups A and C | $1 to $3 |
| Main | 4 setups × (249 attacked + 37 benign) = 1,144 runs | $15 to $50 |
| Optional | setup E, travel | $5 to $15 |
| Reserve | | at least $100 |

Each run sits under the cost harness's `--max-total` cap. The pilot sets the real cost per run. Above
$0.05 a run, setup B goes first, then Slack.

Time is tighter than money. All live runs fall on Nov 1 and 2. At about 30 seconds a pair, one setup over
both suites takes about 2 hours, or 1.2 with suites in parallel.

## Schedule

| Day | Work | Done when |
|---|---|---|
| Thu Oct 29 | Repo, hygiene test, CI, AgentDojo driver. Guard, gateway, labels, tests. Full replay | Done |
| Fri Oct 30 | Labels v2 and the hijack script fix, rerun side by side | Done Oct 29. Next: field-level provenance, replayed against v2 |
| Sat Oct 31 | Live-run CLI with caps. `eval/protocol.yaml`. Rehearse the demo on replay | Protocol committed. One command per setup ready |
| Sun Nov 1 | Tokens start. Live smoke, pilot, then setups A and B | A and B finished by night |
| Mon Nov 2 | Setups C and D. E and travel with time left | Numbers frozen by evening |
| Tue Nov 3 | Results doc, README, pitch numbers, demo rehearsal | A stranger can go from clone to report |
| Wed Nov 4 | Record the video, final hygiene check, make the repo public, submit | Submitted by noon ET |

## Demo, 90 seconds

1. Run one AgentDojo banking task twice. Guard off, the payment goes to an account the user never
   named and AgentDojo marks a breach. Guard on, the log shows
   `blocked send_money.recipient: R1, from the output of read_file`. Show task IDs, never injected text.
2. Show the report: attack success A against D, benign success, cost per task from the harness
   profiler, misses with counts.

Close with 30 seconds on the founder story. The replay version needs no tokens and backs up the live
demo.

## Risks

| Risk | Fallback |
|---|---|
| Muse rejects the `developer` role | Map it to `system` in the gateway on Nov 1 and list the change |
| Muse resists the attack, so baseline success is low | Report it as a finding about Muse. Add AgentDojo's `tool_knowledge` attack. The pitch leads with the zero-token guard and cost |
| R1 blocks too many real tasks | Setup E with rule D. Report both |
| Live runs are slow or rate-limited | Banking only. Slack moves to later |
| Nov 1 and 2 run out | Drop B first, then E and travel. A, C and D are the minimum |
| Labels look tuned to the benchmark | Committed before any run. Travel is a blind check |

## Not before Nov 4

Adaptive attackers, hand-written attacks, dashboards, streaming, hosting, switching between Spark and
Wonder, edits to the cost harness.

## Submission checklist

- [ ] README opens with what Prestige does, the result sentence and a short quickstart
- [ ] README links the cost harness and its results
- [ ] `docs/SECURITY_RESULTS.md`: counts only, misses first, replay and live kept apart, setup and dates
- [ ] CI green, hygiene test passing, secret scan passing
- [ ] Nothing under `runs/` tracked. No transcript or attack text anywhere in history
- [ ] Demo video shows no injected text
- [ ] Pitch numbers match the results doc
- [ ] Repo public. Licenses listed for this repo, the cost harness and AgentDojo (MIT)

## References

- AgentDojo: https://github.com/ethz-spylab/agentdojo (arXiv:2406.13352)
- CaMeL, "Defeating Prompt Injections by Design": arXiv:2503.18813
- OWASP Top 10 for LLM Applications, prompt injection
- Cost engine and results: https://github.com/IrwinJam/agent-cost-harness
