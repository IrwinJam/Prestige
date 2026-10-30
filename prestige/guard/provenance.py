"""Where a value came from.

The system prompt and user messages are trusted. Tool output is untrusted unless its label sets
`trusted_output`. Assistant messages count as neither.

Matching ignores case and spacing. URLs match without scheme or `www.`. Short values must match a
whole token, so "bob" doesn't match "bobby". Long values also match with spaces and hyphens removed,
so a grouped account number still matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from harness.policies import conv
from harness.usage import Protocol

from prestige.guard.labels import ALL, Labels

MIN_CHARS = 3  # shorter values never match
DENSE_MIN_CHARS = 8  # from this length, values also match with spaces and hyphens removed
TRUSTED_ROLES = ("system", "developer", "user")

_URL_PREFIX = re.compile(r"^(?:https?://)?(?:www\.)?")


@dataclass(frozen=True)
class Span:
    text: str
    trusted: bool
    source: str  # "system", "developer", "user", or the name of the tool that returned it
    index: int  # position in the conversation; -1 for Responses `instructions`
    light: str = field(init=False, repr=False)
    dense: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "light", _light(self.text))
        object.__setattr__(self, "dense", _dense(self.text))


def spans(protocol: Protocol, request: dict[str, Any], labels: Labels) -> list[Span]:
    items = conv.items(protocol, dict(request))
    names = conv.tool_names(protocol, items)
    out = []
    if protocol == "responses" and request.get("instructions"):
        out.append(Span(text_of(request["instructions"]), True, "system", -1))
    for i, item in enumerate(items):
        if protocol == "responses" and item.get("type") == "function_call_output":
            tool = names.get(item.get("call_id")) or "unknown"
            out.append(Span(text_of(item.get("output")), labels.get(tool).trusted_output, tool, i))
        elif protocol == "chat_completions" and item.get("role") == "tool":
            tool = names.get(item.get("tool_call_id")) or item.get("name") or "unknown"
            out.append(Span(text_of(item.get("content")), labels.get(tool).trusted_output, tool, i))
        elif item.get("role") in TRUSTED_ROLES:
            out.append(Span(text_of(item.get("content")), True, item["role"], i))
    return out


def text_of(content: Any) -> str:
    """Plain text from a string or from content parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return text_of(content.get("text"))
    if isinstance(content, list):
        return "\n".join(text_of(part) for part in content)
    return str(content)


def sink_values(args: dict[str, Any], sinks: tuple[str, ...] | str) -> list[tuple[str, str]]:
    """(argument, value) for each string or number inside the sink arguments."""
    names = list(args) if sinks == ALL else [s for s in sinks if s in args]
    return [(name, value) for name in names for value in _leaves(args[name])]


def found_in(value: str, span: Span) -> bool:
    v = _value(value)
    if len(v) < MIN_CHARS:
        return False
    if re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", span.light):
        return True
    dv = _dense(v)
    return len(dv) >= DENSE_MIN_CHARS and dv in span.dense


def normalized(value: str) -> str:
    """The compared form. Guard events store its hash, never the value."""
    return _value(value)


def _leaves(value: Any) -> list[str]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, int | float):
        return [str(value)]
    if isinstance(value, list | tuple):
        return [leaf for v in value for leaf in _leaves(v)]
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in _leaves(v)]
    return []


def _light(text: str) -> str:
    return " ".join(text.casefold().split())


def _dense(text: str) -> str:
    return re.sub(r"[\s\-]", "", text.casefold())


def _value(value: str) -> str:
    v = _light(value).strip(" .,;:'\"")
    return _URL_PREFIX.sub("", v).rstrip("/")
