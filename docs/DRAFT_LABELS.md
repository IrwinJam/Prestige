# Drafted labels against hand-written v3

`prestige labels draft` read each suite's tool schemas from AgentDojo and drafted labels with plain
rules on argument names and types. No model call. Compared tool by tool with labels v3.

The rules were written and adjusted while looking at these three suites, so this shows they fit
them. It doesn't show how they do on tools nobody has looked at yet.

| Suite | Tools | Impact matches | High-impact tools caught | Sinks missed | Extra sinks | Tools v3 trusts that the draft doesn't |
|---|---:|---:|---:|---:|---:|---:|
| banking | 11 | 10 / 11 | 5 / 5 | 0 | 0 | 5 |
| slack | 11 | 11 / 11 | 7 / 7 | 0 | 1 | 2 |
| travel | 28 | 28 / 28 | 6 / 6 | 0 | 0 | 4 |

Where the draft differs:

| Suite | Tool | v3 impact | Draft impact | Sinks missed | Extra sinks |
|---|---|---|---|---|---|
| banking | `update_scheduled_transaction` | boundary | state |  |  |
| slack | `add_user_to_channel` | boundary | boundary |  | channel |

The draft leaves off `trusted_output` and `fields` on purpose. A person has to say which tools return only
the user's own data. Until they do, those tools' output counts as untrusted, so the guard blocks more.
