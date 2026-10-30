"""Guard: blocks a tool call whose target came only from untrusted content."""

from prestige.guard.labels import Labels, ToolLabel
from prestige.guard.policy import Finding, Guard

__all__ = ["Finding", "Guard", "Labels", "ToolLabel"]
