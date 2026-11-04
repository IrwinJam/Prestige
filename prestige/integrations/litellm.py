"""The guard as a LiteLLM proxy guardrail.

Teams that already run the LiteLLM proxy can add the guard without a second gateway. It runs after
the model replies. The hook gets the request, with its tool results, and the reply, with its tool calls.
Blocked calls leave the reply and the gateway's notice takes their place, the same as `prestige serve`.

In the proxy's `config.yaml`:

    guardrails:
      - guardrail_name: prestige
        litellm_params:
          guardrail: prestige.integrations.litellm.PrestigeGuardrail
          mode: post_call
          default_on: true
          labels: banking,slack

`labels` takes bundled names or paths, comma separated or as a list. `block` and `flag` pick rules the
way `prestige serve --block` and `--flag` do.

Only chat completions are checked. Other replies pass through unchanged. There's no person to ask in
this hook, so every R1 hit blocks. Nothing here logs or stores a finding's raw value. LiteLLM's
guardrail log gets each finding with a hash and a length in place of the value.

Tested against litellm 1.105.1.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import litellm
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.types.guardrails import GuardrailEventHooks

from prestige.guard import Finding, Guard, Labels

PROTOCOL = "chat_completions"


class PrestigeGuardrail(CustomGuardrail):
    def __init__(self, labels: str | Iterable[str] | None = None, block: str | Iterable[str] = "R1", flag: str | Iterable[str] = "R2", **kwargs: Any):
        names = _names(labels)
        if not names:
            raise ValueError("the prestige guardrail needs `labels`, like banking or a path to a label file")
        self.guard = Guard(Labels.load(*names), block=_names(block), flag=_names(flag))
        kwargs.setdefault("supported_event_hooks", [GuardrailEventHooks.post_call])
        super().__init__(**kwargs)

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict: Any, response: Any) -> Any:
        if not isinstance(response, litellm.ModelResponse):
            return None
        request = {"messages": data.get("messages") or []}
        screened, findings = self.guard.screen(PROTOCOL, request, response.model_dump())
        if findings:
            self._log(findings, data)
        if not any(f.blocked for f in findings):
            return None
        # Swap in the screened choices and keep the rest of the reply, like usage and hidden params.
        response.choices = litellm.ModelResponse(**screened).choices
        return response

    def _log(self, findings: list[Finding], data: dict) -> None:
        rows = [
            {"rule": f.rule, "action": "blocked" if f.blocked else "flagged", "tool": f.tool, "arg": f.arg, "value_hash": f.value_hash, "value_len": f.value_len, "source": f.source}
            for f in findings
        ]
        status = "guardrail_intervened" if any(f.blocked for f in findings) else "guardrail_flagged"
        try:
            self.add_standard_logging_guardrail_information_to_request_data(
                guardrail_json_response=rows, request_data=data, guardrail_status=status, guardrail_provider="prestige", event_type=GuardrailEventHooks.post_call,
            )
        except Exception:  # logging must never break the reply
            pass


def _names(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    parts = value.split(",") if isinstance(value, str) else list(value)
    return [p.strip() for p in parts if p and p.strip()]
