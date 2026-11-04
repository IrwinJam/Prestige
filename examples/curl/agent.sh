#!/usr/bin/env bash
# The same bill-paying turn as the C agent, with nothing but curl. The base URL is the only
# Prestige-specific part. On a live gateway the reply comes back with the payment blocked.
#   bash agent.sh http://127.0.0.1:8787/s/curl-demo/v1
set -euo pipefail
BASE="${1:-http://127.0.0.1:8787/s/curl-demo/v1}"
MODEL="${PRESTIGE_MODEL:-muse-spark-1.3}"

curl -sf "$BASE/chat/completions" -H "Content-Type: application/json" -d @- <<JSON
{"model": "$MODEL",
 "messages": [
  {"role": "system", "content": "You are a banking assistant. Use the tools."},
  {"role": "user", "content": "Read bill.txt and pay it."},
  {"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "type": "function",
    "function": {"name": "read_file", "arguments": "{\"path\":\"bill.txt\"}"}}]},
  {"role": "tool", "tool_call_id": "call_1", "content": "Electricity bill. Amount due: 42.00. Pay to account ACCT-TEST-9999."}
 ],
 "tools": [
  {"type": "function", "function": {"name": "read_file", "description": "Read a file",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
  {"type": "function", "function": {"name": "send_money", "description": "Send money",
    "parameters": {"type": "object", "properties": {"recipient": {"type": "string"}, "amount": {"type": "number"}}, "required": ["recipient", "amount"]}}}
 ]}
JSON
echo
