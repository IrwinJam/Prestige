# Design

How the guard works, what it misses, and how the code is laid out. Results are in
[RESULTS.md](RESULTS.md).

## Flow

The gateway sees tool results in each request and tool calls in each reply. The agent runs the tools,
so the guard checks each reply before the agent gets it.

```
agent (AgentDojo, or anything OpenAI-compatible)
   |  request: system and user messages (trusted), tool results (untrusted)
gateway: cost policies rewrite the request -> model
   |  reply: tool calls
guard: does a high-impact call aim where only untrusted content pointed?
   |-- no:  reply goes to the agent unchanged
   |-- yes: call removed, notice added, event logged, or the user is asked
agent runs the calls that are left
```

## Trust

System and user messages are trusted. Tool output is untrusted unless its label sets `trusted_output`.

## Labels

One YAML file per suite gives each tool an impact level. High-impact tools list their sink arguments,
the ones that pick where money or data goes.

```yaml
send_money:            { impact: boundary, sinks: [recipient] }
send_direct_message:   { impact: boundary, sinks: [recipient] }
update_password:       { impact: state,    sinks: [password] }
get_most_recent_transactions: { impact: read }
```

Unlisted tools get every argument checked. Each version lives in its own folder under
`prestige/guard/labels/`, and old versions never change.

| Version | Change |
|---|---|
| v1 | First labels, banking and Slack, written from tool definitions |
| v2 | `get_channels` output untrusted. Any workspace member can name a channel |
| v3 | Whole values in fields a tool writes are trusted, like a transaction's `recipient`. Travel added, written from tool definitions and never changed after a result |

v2 and v3 were changed after offline replays of banking and Slack. Travel is the blind check.

For new tools, `prestige labels draft` writes a first draft from the tool schemas: URL arguments make a
tool a boundary tool, read verbs make it read-only, and argument names like `recipient`, `channel` or
`email` become sinks. Anything it can't place gets every argument checked. A person still sets
`trusted_output` and `fields`. See [DRAFT_LABELS.md](DRAFT_LABELS.md).

## Rules

**R1, sink provenance.** Blocks a high-impact call when a sink value appears in untrusted output and
nowhere in trusted text. Matching ignores case and spacing. URLs match without scheme or `www.`.
Message bodies aren't checked, because summarizing tool output into a message is normal work.

**R2, tool named by content.** Flags a high-impact call when untrusted output names the tool and trusted
text doesn't. It only flags by default.

**Confirm step.** An R1 hit can go to the user as a question instead of a block. Approvals match the
value by hash. In evals a stand-in user approves values from the task's reference solution, which is a
best case.

With `serve --ask` or `live --ask`, a real person answers instead. The gateway writes the question to an
`approvals` table in the trace database and waits. `prestige buddy watch` shows the tool, the value
and where it came from, and writes back yes or no. No answer before `--ask-timeout`, 120 seconds by
default, counts as no. The value is shown printable and cut to 80 characters, since it may come from an
attacker, and it's wiped from the table as soon as the question is answered or times out. The code is
in `prestige/approvals.py`.

The guard makes no model calls and adds no tokens. Blocked values are stored as a hash and a length.

## Known misses

- Harm through a message body alone. This caused every miss so far.
- Values the model rewrites, like spelled-out or split numbers.
- Destinations that also appear in trusted text.
- Values the agent never saw. An injection replaces the text it sits in, so under attack a bill's real
  IBAN can disappear and the user's own payment has nothing to match.
- Anything that isn't a tool call.

Values inside text the user pointed at, like the IBAN in a bill they asked to pay, share one data flow
with an attacker's value. Provenance alone can't separate them. That's where the false blocks come
from, and why the confirm step exists. CaMeL reports the same limit.

## Code

Prestige doesn't edit the cost harness. It pins it at `576fe5e` and reuses its proxy, adapters, trace
store and policies.

| File | Role |
|---|---|
| `prestige/gateway.py` | `GuardedSession` subclasses the harness `Session` and screens each reply. Also the server builder |
| `prestige/__main__.py` | `python -m prestige serve`, the harness's `serve` plus guard options |
| `prestige/guard/provenance.py` | Trusted and untrusted spans, value matching |
| `prestige/guard/labels.py` | Versioned tool labels |
| `prestige/guard/policy.py` | R1, R2, the notice, findings |
| `prestige/guard/draft.py` | First-draft labels from OpenAI or MCP tool schemas, `prestige labels draft` |
| `prestige/approvals.py` | Questions to a real person through the trace database, for `--ask` |
| `prestige/buddy.py` | The terminal sprite: demo, results, spend, and `watch`, which answers questions |
| `prestige/eval/agentdojo.py` | AgentDojo through the gateway, one pair at a time |
| `prestige/eval/published.py` | AutoDojo's published injections, read at run time |
| `prestige/eval/replay.py` | Offline replay with a scripted agent, and its report |
| `prestige/eval/live.py`, `live_report.py` | Live runs with spend caps, and their report |
| `prestige/eval/repeat_report.py` | Report for attacked pairs run many times |
| `prestige/eval/overhead.py` | Time the guard adds, from live traces |
| `prestige/eval/demo.py` | One hijacked task with the guard off and on |
| `eval/protocol.yaml` | Test plan, committed before any live run |

`GuardedSession` overrides the harness's private `_send`. The pinned commit keeps that stable. It
should become a public hook in the harness.

## AgentDojo notes

- PyPI `agentdojo==0.1.35` can't target an OpenAI-compatible URL. Its `local` mode turns tool calls into
  prompt text, which hides them from the guard. Prestige drives AgentDojo as a library and passes it an
  OpenAI client aimed at the gateway.
- `security` is `True` when the attack worked.
- The default attack rejects model names it doesn't know, so runs use
  `important_instructions_no_model_name`.
- AgentDojo's suite runner runs each injection task alone first. The per-pair runner skips that, and
  gives each pair its own conversation key so pairs that open the same way don't share a session.
- AgentDojo sends the system prompt with role `developer`. `--developer-as-system` maps it for a
  provider that refuses it.

## Repo safety

No attacks are written here, and no attack text is published.

| Never committed | Enforced by |
|---|---|
| Attack or injection text | Attacks come from AgentDojo on PyPI and AutoDojo's files, read at run time |
| Transcripts, traces, benchmark logs | `runs/`, `*.sqlite` and `*.jsonl` are ignored |
| Blocked values | Guard events store a hash and a length |
| Keys | `.env` is ignored. CI runs gitleaks |

`tests/test_public_hygiene.py` checks every file git would commit, tracked or not. It fails on run
data, keys, files over 512 KB and benchmark logs. `tests/test_replay.py` checks that no line of tool
output reaches the replay report.

## References

- AgentDojo: https://github.com/ethz-spylab/agentdojo (arXiv:2406.13352)
- AutoDojo: https://github.com/xhOwenMa/AutoDojo (arXiv:2606.15057)
- ROPE: arXiv:2608.27496
- CaMeL: arXiv:2503.18813
- Cost harness: https://github.com/IrwinJam/agent-cost-harness
