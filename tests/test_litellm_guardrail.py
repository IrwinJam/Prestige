"""The LiteLLM guardrail, run on scripted replies. No proxy and no model calls."""

import asyncio
import json
import os

import pytest

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # no price map download on import
litellm = pytest.importorskip("litellm")

from fixtures import LABELS, MARKER, read_then, reply  # noqa: E402

from prestige.guard import Guard  # noqa: E402
from prestige.integrations.litellm import PrestigeGuardrail  # noqa: E402

PAYS_MARKER = ("c2", "send_money", {"recipient": MARKER, "amount": 10})


def run(guardrail, request, raw_reply):
    response = litellm.ModelResponse(**raw_reply, model="test-model")
    out = asyncio.run(guardrail.async_post_call_success_hook(data=request, user_api_key_dict=None, response=response))
    return out or response


def logged(request):
    return request.get("metadata", {}).get("standard_logging_guardrail_information") or []


def test_a_call_paying_an_account_from_tool_output_is_removed():
    request = read_then(f"Due: 10.00 to {MARKER}")
    out = run(PrestigeGuardrail(labels="banking", guardrail_name="prestige"), request, reply(PAYS_MARKER))
    message = out.choices[0].message
    assert not message.tool_calls
    assert out.choices[0].finish_reason == "stop"
    assert message.content.startswith("Blocked send_money")


def test_the_notice_matches_the_gateway():
    request = read_then(f"Due: 10.00 to {MARKER}")
    expected, _ = Guard(LABELS).screen("chat_completions", request, reply(PAYS_MARKER))
    out = run(PrestigeGuardrail(labels="banking"), request, reply(PAYS_MARKER))
    assert out.choices[0].message.content == expected["choices"][0]["message"]["content"]


def test_a_clean_reply_passes_unchanged():
    request = read_then("Due: 10.00, paid in full.")
    raw = reply(("c2", "get_balance", {}), content="Checking.")
    response = litellm.ModelResponse(**raw, model="test-model")
    before = response.model_dump()
    out = asyncio.run(PrestigeGuardrail(labels="banking").async_post_call_success_hook(data=request, user_api_key_dict=None, response=response))
    assert out is None
    assert response.model_dump() == before
    assert logged(request) == []


def test_a_value_the_user_typed_goes_through():
    request = read_then(f"Due: 10.00 to {MARKER}")
    request["messages"][1]["content"] = f"Pay my bill to {MARKER}."
    out = run(PrestigeGuardrail(labels="banking"), request, reply(PAYS_MARKER))
    assert out.choices[0].message.tool_calls[0].function.name == "send_money"


def test_the_log_never_holds_the_value():
    request = read_then(f"Due: 10.00 to {MARKER}")
    run(PrestigeGuardrail(labels="banking"), request, reply(PAYS_MARKER))
    entries = logged(request)
    assert entries
    dump = json.dumps(entries, default=str)
    assert "send_money" in dump and MARKER.casefold() not in dump.casefold()


def test_labels_from_a_path_and_a_list(tmp_path):
    path = tmp_path / "mine.yaml"
    path.write_text("tools:\n  read_file: { impact: read }\n  send_money: { impact: boundary, sinks: [recipient] }\n", encoding="utf-8")
    for labels in (str(path), [str(path)]):
        out = run(PrestigeGuardrail(labels=labels), read_then(f"to {MARKER}"), reply(PAYS_MARKER))
        assert not out.choices[0].message.tool_calls


def test_labels_are_required():
    with pytest.raises(ValueError):
        PrestigeGuardrail()


def test_other_replies_pass_through():
    marker = object()
    assert asyncio.run(PrestigeGuardrail(labels="banking").async_post_call_success_hook(data={}, user_api_key_dict=None, response=marker)) is None
