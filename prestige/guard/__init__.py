"""Guard: blocks a tool call whose target came only from untrusted content."""

from prestige.guard.labels import Labels, ToolLabel
from prestige.guard.policy import MENTION, ORIGIN, Finding, Guard, rule_name

__all__ = ["MENTION", "ORIGIN", "Finding", "Guard", "Labels", "ToolLabel", "rule_name"]
