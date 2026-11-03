"""Published optimized injections, loaded at run time. Nothing from them lives in this repo.

    python -m prestige.eval.live --attack "autodojo:<AutoDojo>/agentdojo/variant_generation/variants/{suite}/anthropic/claude-haiku-4.5/no_defense/injections.json" ...

AutoDojo (MIT, github.com/xhOwenMa/AutoDojo, arXiv:2606.15057) publishes injections optimized against
named models on AgentDojo's suites. One file per suite, target model and defense. This loader follows
their own `autodojo_attack.py`: one text per injection task and vector, and AgentDojo's standard
wrapper when optimization didn't change the original.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentdojo.attacks.base_attacks import BaseAttack, get_model_name_from_pipeline
from agentdojo.base_tasks import BaseInjectionTask, BaseUserTask

PREFIX = "autodojo:"
USER_NAME = "Emma Johnson"  # AgentDojo's user in every suite


def load(path: str | Path, suite_name: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("suite") != suite_name:
        raise ValueError(f"{path} holds injections for {data.get('suite')!r}, not {suite_name!r}")
    return data["injection_tasks"]


def yaml_escape(text: str) -> str:
    """AgentDojo splices injections into YAML double-quoted strings with str.format()."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


class PublishedAttack(BaseAttack):
    name = "autodojo"

    def __init__(self, task_suite: Any, target_pipeline: Any, path: str | Path, variant: int = 0) -> None:
        super().__init__(task_suite, target_pipeline)
        self.cells = load(path, task_suite.name)
        self.variant = variant
        self.model_name = get_model_name_from_pipeline(target_pipeline)

    def attack(self, user_task: BaseUserTask, injection_task: BaseInjectionTask) -> dict[str, str]:
        # Imported here so the wrapper text stays in AgentDojo's package.
        from agentdojo.attacks.important_instructions_attacks import ImportantInstructionsAttack

        by_vector = self.cells.get(injection_task.ID, {})
        out = {}
        for vector in self.get_injection_candidates(user_task):
            entry = by_vector.get(vector, {})
            variants = entry.get("variants") or []
            text = variants[self.variant] if self.variant < len(variants) else injection_task.GOAL
            if text.strip() == (entry.get("original") or injection_task.GOAL).strip():
                text = ImportantInstructionsAttack._JB_STRING.format(user=USER_NAME, model=self.model_name, goal=text)
            out[vector] = yaml_escape(text)
        return out


def make(name: str, task_suite: Any, pipeline: Any) -> BaseAttack | None:
    """`autodojo:<path>` gives a PublishedAttack. `{suite}` in the path becomes the suite's name.
    Anything else is left to AgentDojo's registry."""
    if not name.startswith(PREFIX):
        return None
    return PublishedAttack(task_suite, pipeline, name[len(PREFIX):].replace("{suite}", task_suite.name))
