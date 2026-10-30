"""Neutral test data.

No instruction text anywhere. The guard judges where a value came from, so a marker in tool output
and a scripted reply are enough.
"""

from __future__ import annotations

import json
from typing import Any

from prestige.guard import Labels, ToolLabel

MARKER = "ACCT-TEST-0001"
OTHER = "ACCT-TEST-0002"

LABELS = Labels(
    {
        "send_money": ToolLabel("boundary", ("recipient",)),
        "update_password": ToolLabel("state", ("password",)),
        "read_file": ToolLabel("read"),
        "get_iban": ToolLabel("read", trusted_output=True),
        "get_balance": ToolLabel("read", trusted_output=True),
    },
    default=ToolLabel("state", "*"),
)

SYSTEM = {"role": "system", "content": "You are a banking assistant."}


def user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def called(call_id: str, name: str, **args: Any) -> dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": [_call(call_id, name, args)]}


def tool(call_id: str, content: Any) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def chat(*messages: dict[str, Any]) -> dict[str, Any]:
    return {"model": "test-model", "messages": list(messages)}


def reply(*calls: tuple[str, str, dict[str, Any]], content: str | None = None) -> dict[str, Any]:
    message = {"role": "assistant", "content": content, "tool_calls": [_call(i, n, a) for i, n, a in calls] or None}
    finish = "tool_calls" if calls else "stop"
    return {"choices": [{"index": 0, "message": message, "finish_reason": finish}]}


def read_then(text: str) -> dict[str, Any]:
    """A conversation where a file read returned `text`."""
    return chat(SYSTEM, user("Pay my bill."), called("c1", "read_file", file_path="bill.txt"), tool("c1", text))


def _call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
