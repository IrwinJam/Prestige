"""First-draft labels from tool schemas, for a person to review.

    prestige labels draft tools.json > labels/mine.yaml

Takes OpenAI-style tools (`{"type": "function", "function": {...}}`) or MCP tools (`{"name", "inputSchema"}`),
as a JSON list or `{"tools": [...]}`. Plain rules on names and types. No model call.

What it can't know: which tools return only the user's own data (`trusted_output`) and which output
fields a tool writes itself (`fields`). Both are left off, which is the safe side: more blocks, not
fewer. The header says so.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

URL = re.compile(r"(^|_)(url|uri|link|endpoint|webhook)s?$")
WHO = re.compile(r"(^|_)(recipients?|to|cc|bcc|users?|user_email|emails?|channels?|participants?|iban|account|phone|address)$")
# Which account the agent acts as. Always checked, whatever else the tool does.
CREDENTIAL = re.compile(r"(^|_)(token|api_key|key|secret|password|passphrase|credentials?|auth)s?$")
FREE_TEXT = re.compile(r"(^|_)(body|content|text|message|subject|description|title|note|notes|query|prompt|comment)s?$")
WHEN = re.compile(r"(^|_)(date|day|time|start|end|when|duration|recurring)s?($|_)")
READ_VERB = re.compile(r"^(get|read|list|search|find|check|view|show|lookup|fetch|count|query)_")
CHANGE_VERB = re.compile(r"^(update|delete|remove|cancel|set|change|edit|rename|archive|reset|revoke)_")


def tools_from(data: Any) -> list[tuple[str, dict[str, Any]]]:
    """(name, JSON schema of its arguments) for each tool, from OpenAI or MCP shapes."""
    items = data.get("tools", data) if isinstance(data, dict) else data
    out = []
    for item in items:
        fn = item.get("function", item)
        schema = fn.get("parameters") or fn.get("inputSchema") or fn.get("input_schema") or {}
        out.append((fn["name"], schema))
    return out


def _args(schema: dict[str, Any]) -> dict[str, str]:
    """Argument name to a simple type: string, number, boolean, array, object."""
    props = schema.get("properties") or {}
    kinds = {}
    for name, spec in props.items():
        kind = spec.get("type") or next((s.get("type") for s in spec.get("anyOf", []) if s.get("type") != "null"), "string")
        if kind == "array":
            kind = "array:" + ((spec.get("items") or {}).get("type") or "string")
        kinds[name] = kind
    return kinds


def label(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    args = _args(schema)
    texty = [a for a, k in args.items() if k in ("string", "array:string", "integer") and not FREE_TEXT.search(a) and not WHEN.search(a)]
    urls = [a for a in args if URL.search(a)]
    creds = [a for a in args if CREDENTIAL.search(a)]
    who = [a for a in args if WHO.search(a)] + [a for a in creds if not WHO.search(a)]
    if urls:  # opening a URL sends data out, whatever the verb
        return {"impact": "boundary", "sinks": urls + creds}
    if READ_VERB.match(name) or not args:  # reading a channel or a user's inbox sends nothing
        return {"impact": "read"}
    if CHANGE_VERB.match(name):
        return {"impact": "state", "sinks": who or texty or "*"}
    if who:
        return {"impact": "boundary", "sinks": who}
    return {"impact": "boundary", "sinks": texty or "*"}


def draft(tools: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    return {name: label(name, schema) for name, schema in tools}


def to_yaml(labels: dict[str, dict[str, Any]], source: str) -> str:
    lines = [
        f"# Drafted by `prestige labels draft` from {source}. Review every line before use.",
        "# Not set by the draft: trusted_output (tools that return only the user's own data) and fields",
        "# (output fields the tool writes itself). Without them the guard blocks more, never less.",
        "",
        'default: { impact: state, sinks: "*" }',
        "",
        "tools:",
    ]
    for name, spec in labels.items():
        parts = [f"impact: {spec['impact']}"]
        if "sinks" in spec:
            parts.append("sinks: " + (json.dumps(spec["sinks"]) if spec["sinks"] == "*" else "[" + ", ".join(spec["sinks"]) + "]"))
        lines.append(f"  {name}: {{ {', '.join(parts)} }}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="prestige labels draft", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tools", help="JSON file with OpenAI or MCP tool definitions")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.tools).read_text(encoding="utf-8"))
    print(to_yaml(draft(tools_from(data)), Path(args.tools).name), end="")
    return 0
