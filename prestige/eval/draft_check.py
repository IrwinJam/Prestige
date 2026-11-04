"""How close drafted labels come to the hand-written v3 labels, on AgentDojo's own tool schemas.

    python -m prestige.eval.draft_check --md docs/DRAFT_LABELS.md

A missed sink is the costly kind: the guard wouldn't check that argument. An extra sink only risks a
false block, which the confirm step turns into a question.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from prestige.eval.agentdojo import suite
from prestige.guard.draft import draft
from prestige.guard.labels import Labels

SUITES = ("banking", "slack", "travel")


def compare(suite_name: str) -> dict:
    s = suite(suite_name)
    tools = [(t.name, t.parameters.model_json_schema()) for t in s.tools]
    drafted = draft(tools)
    hand = Labels.load(f"{suite_name}@v3")
    rows = []
    for name, _ in tools:
        h, d = hand.get(name), drafted[name]
        h_sinks = set() if not h.high_impact else ({"*"} if h.sinks == "*" else set(h.sinks))
        d_sinks = set() if d["impact"] == "read" else ({"*"} if d.get("sinks") == "*" else set(d.get("sinks", [])))
        missed = set() if "*" in d_sinks else h_sinks - d_sinks - {"*"}
        extra = set() if "*" in h_sinks else d_sinks - h_sinks
        rows.append((name, h.impact, d["impact"], sorted(missed), sorted(extra), h.trusted_output or bool(h.fields)))
    return {"suite": suite_name, "rows": rows}


def render(results: list[dict]) -> str:
    lines = [
        "# Drafted labels against hand-written v3",
        "",
        "`prestige labels draft` read each suite's tool schemas from AgentDojo and drafted labels with plain",
        "rules on argument names and types. No model call. Compared tool by tool with labels v3.",
        "",
        "The rules were written and adjusted while looking at these three suites, so this shows they fit",
        "them. It doesn't show how they do on tools nobody has looked at yet.",
        "",
        "| Suite | Tools | Impact matches | High-impact tools caught | Sinks missed | Extra sinks | Tools v3 trusts that the draft doesn't |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    details = []
    for r in results:
        rows = r["rows"]
        high = [x for x in rows if x[1] != "read"]
        caught = [x for x in high if x[2] != "read"]
        missed = sum(len(x[3]) for x in rows)
        extra = sum(len(x[4]) for x in rows)
        trusted = sum(1 for x in rows if x[5])
        lines.append(f"| {r['suite']} | {len(rows)} | {sum(1 for x in rows if x[1] == x[2])} / {len(rows)} | {len(caught)} / {len(high)} | {missed} | {extra} | {trusted} |")
        for name, h, d, m, e, _ in rows:
            if h != d or m or e:
                details.append(f"| {r['suite']} | `{name}` | {h} | {d} | {', '.join(m) or ''} | {', '.join(e) or ''} |")
    lines += ["", "Where the draft differs:", "", "| Suite | Tool | v3 impact | Draft impact | Sinks missed | Extra sinks |", "|---|---|---|---|---|---|", *details]
    lines += [
        "",
        "The draft leaves off `trusted_output` and `fields` on purpose. A person has to say which tools return only",
        "the user's own data. Until they do, those tools' output counts as untrusted, so the guard blocks more.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.draft_check", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--md", help="write here. Default: print")
    args = parser.parse_args(argv)
    report = render([compare(s) for s in SUITES])
    if args.md:
        Path(args.md).write_text(report, encoding="utf-8")
        print(f"report: {args.md}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
