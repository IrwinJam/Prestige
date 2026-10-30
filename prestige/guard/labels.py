"""Tool labels: an impact level per tool, and the arguments that pick where things go.

One YAML file per suite, in one folder per version. `Labels.load("banking")` loads the latest version.
`Labels.load("banking@v1")` picks one. Paths work too. Old versions stay unchanged, so earlier results
can be reproduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

IMPACTS = ("read", "state", "boundary")
ALL = "*"  # as `sinks`: every argument is a sink
VERSIONS = ("v1", "v2")
LATEST = VERSIONS[-1]


class LabelError(ValueError):
    pass


@dataclass(frozen=True)
class ToolLabel:
    impact: str
    sinks: tuple[str, ...] | str = ()
    trusted_output: bool = False

    @property
    def high_impact(self) -> bool:
        return self.impact != "read"


@dataclass(frozen=True)
class Labels:
    tools: dict[str, ToolLabel]
    default: ToolLabel

    def get(self, name: str) -> ToolLabel:
        return self.tools.get(name, self.default)

    @classmethod
    def load(cls, *sources: str | Path) -> Labels:
        """Load and merge label files. Each one is a path or the name of a bundled file, like "banking"."""
        if not sources:
            raise LabelError("no label files given")
        tools: dict[str, ToolLabel] = {}
        default = None
        for source in sources:
            data = yaml.safe_load(_read(source))
            if not isinstance(data, dict) or set(data) - {"default", "tools"}:
                raise LabelError(f"{source}: expected only `default` and `tools`")
            file_default = _label(f"{source}: default", data.get("default") or {"impact": "state", "sinks": ALL})
            if default is not None and file_default != default:
                raise LabelError(f"{source}: its default differs from an earlier file's")
            default = file_default
            for name, raw in (data.get("tools") or {}).items():
                label = _label(f"{source}: {name}", raw)
                if name in tools and tools[name] != label:
                    raise LabelError(f"{source}: {name} is labelled differently in an earlier file")
                tools[name] = label
        return cls(tools, default)


def _read(source: str | Path) -> str:
    path = Path(source)
    if path.suffix in (".yaml", ".yml") or path.exists():
        return path.read_text(encoding="utf-8")
    name, _, version = str(source).partition("@")
    version = version or LATEST
    if version not in VERSIONS:
        raise LabelError(f"unknown label version {version!r}; choose from {VERSIONS}")
    bundled = resources.files("prestige.guard") / "labels" / version / f"{name}.yaml"
    if not bundled.is_file():
        raise LabelError(f"no label file {source!r}, and no bundled one by that name")
    return bundled.read_text(encoding="utf-8")


def _label(where: str, raw: Any) -> ToolLabel:
    if not isinstance(raw, dict) or set(raw) - {"impact", "sinks", "trusted_output"}:
        raise LabelError(f"{where}: expected `impact`, and optionally `sinks` and `trusted_output`")
    impact = raw.get("impact")
    if impact not in IMPACTS:
        raise LabelError(f"{where}: impact must be one of {IMPACTS}, got {impact!r}")
    sinks = raw.get("sinks", ())
    if sinks != ALL:
        if not isinstance(sinks, list | tuple) or not all(isinstance(s, str) for s in sinks):
            raise LabelError(f'{where}: sinks must be a list of argument names or "*"')
        sinks = tuple(sinks)
    if impact == "read" and sinks:
        raise LabelError(f"{where}: read tools can't have sinks")
    return ToolLabel(impact, sinks, bool(raw.get("trusted_output", False)))
