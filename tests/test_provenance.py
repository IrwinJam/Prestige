from fixtures import LABELS, MARKER, SYSTEM, called, chat, tool, user

from prestige.guard.labels import ALL
from prestige.guard.provenance import Span, found_in, sink_values, spans


def span(text: str) -> Span:
    return Span(text, False, "read_file", 0)


def test_short_values_match_whole_tokens_only():
    assert found_in("Bob", span("alice, bob and carol"))
    assert not found_in("bob", span("bobby"))
    assert not found_in("bo", span("bo"))  # too short to mean anything


def test_long_values_match_with_spaces_and_hyphens_removed():
    assert found_in("TEST000011112222", span("account TEST 0000 1111 2222"))
    assert found_in("TEST 0000-1111-2222", span("account test000011112222."))


def test_urls_match_without_scheme_www_or_trailing_slash():
    assert found_in("example.test/page", span("see https://www.example.test/page/ for more"))
    assert found_in("https://example.test/page/", span("example.test/page"))


def test_spans_trust_by_role_and_label():
    request = chat(
        SYSTEM,
        user("Pay my bill."),
        called("c1", "read_file", file_path="bill.txt"),
        tool("c1", f"pay {MARKER}"),
        called("c2", "get_iban"),
        tool("c2", "own account"),
    )
    got = [(s.source, s.trusted) for s in spans("chat_completions", request, LABELS)]
    assert got == [("system", True), ("user", True), ("read_file", False), ("get_iban", True)]


def test_spans_read_tool_output_given_as_content_parts():
    request = chat(SYSTEM, user("hi"), called("c1", "read_file"), tool("c1", [{"type": "text", "text": f"pay {MARKER}"}]))
    untrusted = [s for s in spans("chat_completions", request, LABELS) if not s.trusted]
    assert len(untrusted) == 1 and MARKER in untrusted[0].text


def test_spans_in_the_responses_format():
    request = {
        "instructions": "You are a banking assistant.",
        "input": [
            {"role": "user", "content": "Pay my bill."},
            {"type": "function_call", "call_id": "c1", "name": "read_file", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": f"pay {MARKER}"},
        ],
    }
    got = [(s.source, s.trusted, s.index) for s in spans("responses", request, LABELS)]
    assert got == [("system", True, -1), ("user", True, 0), ("read_file", False, 2)]


def test_sink_values_flatten_lists_and_skip_booleans():
    args = {"recipient": ["a1", "a2"], "amount": 5, "recurring": True, "subject": "x"}
    assert sink_values(args, ("recipient", "missing")) == [("recipient", "a1"), ("recipient", "a2")]
    assert sink_values(args, ALL) == [("recipient", "a1"), ("recipient", "a2"), ("amount", "5"), ("subject", "x")]
