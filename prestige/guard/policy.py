"""Guard rules, and what a blocked reply looks like.

R1, sink provenance: a sink value appears in untrusted tool output and nowhere in trusted text.
R2, tool named by content: untrusted output names the tool and trusted text doesn't. Flagged by default.

A person can approve a call the rule would block. `approve` gets the finding. Its `value` is there so
the person can see what they're approving, and nothing stores it. Without it, every R1 hit blocks. A user who names the value in a message gets the same
result, since that puts the value in trusted text.

A blocked call leaves the reply before the agent sees it. A short notice takes its place. The notice
names the call and the source, never the value, which may be attacker text. Findings store a hash and
a length.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from harness.policies import conv
from harness.usage import Protocol

from prestige.guard import provenance
from prestige.guard.labels import Labels
from prestige.guard.provenance import Span

RULES = ("R1", "R2")
Approver = Callable[["Finding"], bool]


@dataclass(frozen=True)
class Finding:
    rule: str
    tool: str
    call_id: str
    arg: str | None  # sink argument for R1, None for R2
    value_hash: str | None
    value_len: int | None
    source: str  # tool whose output held the value or the tool name
    source_index: int
    blocked: bool
    confirmed: bool = False  # a person approved it, so it went through
    # The raw value, only so a person can see what they're approving. Never stored or logged.
    value: str | None = field(default=None, repr=False, compare=False)


class Guard:
    def __init__(self, labels: Labels, *, block: Iterable[str] = ("R1",), flag: Iterable[str] = ("R2",)):
        self.labels = labels
        self.block = frozenset(block)
        self.flag = frozenset(flag) - self.block
        unknown = (self.block | self.flag) - set(RULES)
        if unknown:
            raise ValueError(f"unknown rules {sorted(unknown)}; choose from {RULES}")

    def check(self, protocol: Protocol, request: dict[str, Any], response: dict[str, Any], skip: Iterable[str] = ()) -> list[Finding]:
        """Findings for the tool calls in `response`, judged against `request`."""
        active = self.block | self.flag
        if not active:
            return []
        skip = set(skip)
        all_spans = provenance.spans(protocol, request, self.labels)
        trusted = [s for s in all_spans if s.trusted]
        untrusted = [s for s in all_spans if not s.trusted]
        findings = []
        for call in conv.response_tool_calls(protocol, response):
            label = self.labels.get(call.name)
            if call.name in skip or not label.high_impact:
                continue
            if "R1" in active:
                for arg, value in provenance.sink_values(_args(call.arguments), label.sinks):
                    source = _first(value, untrusted)
                    if source is not None and _first(value, trusted) is None:
                        norm = provenance.normalized(value)
                        findings.append(Finding(
                            "R1", call.name, call.call_id, arg, _hash(norm), len(value), source.source, source.index, "R1" in self.block, value=value,
                        ))
            if "R2" in active:
                source = _first_name(call.name, untrusted)
                if source is not None and _first_name(call.name, trusted) is None:
                    findings.append(Finding("R2", call.name, call.call_id, None, None, None, source.source, source.index, "R2" in self.block))
        return findings

    def screen(self, protocol: Protocol, request: dict[str, Any], response: dict[str, Any], skip: Iterable[str] = (), approve: Approver | None = None) -> tuple[dict[str, Any], list[Finding]]:
        """The reply the agent should see, with blocked calls removed, plus findings."""
        findings = self.check(protocol, request, response, skip)
        if approve:
            findings = [replace(f, blocked=False, confirmed=True) if f.blocked and approve(f) else f for f in findings]
        blocked = [f for f in findings if f.blocked]
        if not blocked:
            return response, findings
        return _without_calls(protocol, response, {f.call_id for f in blocked}, notice(blocked)), findings


def notice(blocked: list[Finding]) -> str:
    lines = []
    seen = set()
    for f in blocked:
        if f.rule == "R1":
            line = f"Blocked {f.tool}: {f.arg} came from {f.source} output, not from the user."
        else:
            line = f"Blocked {f.tool}: only {f.source} output asked for it."
        if line not in seen:
            seen.add(line)
            lines.append(line)
    lines.append("Ask the user before trying again.")
    return " ".join(lines)


def _args(arguments: str) -> dict[str, Any]:
    try:
        args = json.loads(arguments or "{}")
    except ValueError:
        return {}
    return args if isinstance(args, dict) else {}


def _first(value: str, spans: list[Span]) -> Span | None:
    return next((s for s in spans if provenance.found_in(value, s)), None)


def _first_name(tool: str, spans: list[Span]) -> Span | None:
    variants = {tool, tool.replace("_", " ")}
    return next((s for s in spans if any(provenance.found_in(v, s) for v in variants)), None)


def value_hash(value: str) -> str:
    """The hash a finding carries for this raw value."""
    return _hash(provenance.normalized(value))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _without_calls(protocol: Protocol, response: dict[str, Any], call_ids: set[str], text: str) -> dict[str, Any]:
    if protocol == "responses":
        output = [o for o in response.get("output") or [] if not (o.get("type") == "function_call" and o.get("call_id") in call_ids)]
        output.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
        return {**response, "output": output}
    choices = []
    for choice in response.get("choices") or []:
        message = dict(choice.get("message") or {})
        calls = [c for c in message.get("tool_calls") or [] if c.get("id") not in call_ids]
        message["tool_calls"] = calls or None
        message["content"] = "\n\n".join(t for t in (provenance.text_of(message.get("content")), text) if t)
        finish = choice.get("finish_reason") if calls else "stop"
        choices.append({**choice, "message": message, "finish_reason": finish})
    return {**response, "choices": choices}
