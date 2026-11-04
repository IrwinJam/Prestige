import json

from prestige.__main__ import main
from prestige.guard import Labels
from prestige.guard.draft import draft, to_yaml, tools_from

OPENAI = [
    {"type": "function", "function": {"name": "send_money", "parameters": {"type": "object", "properties": {"recipient": {"type": "string"}, "amount": {"type": "number"}, "subject": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "get_balance", "parameters": {"type": "object", "properties": {}}}},
]
MCP = {"tools": [
    {"name": "fetch_page", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}}},
    {"name": "read_channel", "inputSchema": {"type": "object", "properties": {"channel": {"type": "string"}}}},
    {"name": "update_password", "inputSchema": {"type": "object", "properties": {"password": {"type": "string"}}}},
    {"name": "do_thing", "inputSchema": {"type": "object", "properties": {"note": {"type": "string"}}}},
]}


def test_openai_and_mcp_shapes():
    labels = draft(tools_from(OPENAI) + tools_from(MCP))
    assert labels["send_money"] == {"impact": "boundary", "sinks": ["recipient"]}
    assert labels["get_balance"] == {"impact": "read"}
    assert labels["fetch_page"] == {"impact": "boundary", "sinks": ["url"]}  # a URL beats the read verb
    assert labels["read_channel"] == {"impact": "read"}
    assert labels["update_password"] == {"impact": "state", "sinks": ["password"]}
    assert labels["do_thing"] == {"impact": "boundary", "sinks": "*"}  # unknown means check everything


def test_draft_loads_as_real_labels(tmp_path):
    path = tmp_path / "mine.yaml"
    path.write_text(to_yaml(draft(tools_from(OPENAI)), "tools.json"), encoding="utf-8")
    labels = Labels.load(str(path))
    assert labels.get("send_money").sinks == ("recipient",)
    assert labels.get("get_balance").high_impact is False


def test_cli(tmp_path, capsys):
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(MCP), encoding="utf-8")
    assert main(["labels", "draft", str(path)]) == 0
    assert "fetch_page: { impact: boundary, sinks: [url] }" in capsys.readouterr().out
