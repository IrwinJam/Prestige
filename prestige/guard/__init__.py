"""The guard: blocks a tool call when where it's aimed came only from untrusted content."""

from prestige.guard.labels import Labels, ToolLabel
from prestige.guard.policy import Finding, Guard

__all__ = ["Finding", "Guard", "Labels", "ToolLabel"]
