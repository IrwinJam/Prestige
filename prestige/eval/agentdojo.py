"""AgentDojo through the gateway.

AgentDojo 0.1.35 can't target an arbitrary OpenAI-compatible URL. Its pipeline does accept a model
object, so it gets an OpenAI client aimed at the gateway. Tool calling and defenses stay as published.

Logs go under `runs/`, which is never committed. They contain the benchmark's injected text.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import openai
from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import (
    SuiteResults,
    benchmark_suite_with_injections,
    benchmark_suite_without_injections,
    run_task_with_injection_tasks,
    run_task_without_injection_tasks,
)
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.task_suite.task_suite import TaskSuite

from prestige.eval import published

BENCHMARK_VERSION = "v1.2.2"
# The default attack rejects model names it doesn't know, Muse included. This published variant
# leaves the name out.
DEFAULT_ATTACK = "important_instructions_no_model_name"


def build_pipeline(base_url: str, model: str, defense: str | None = None) -> AgentPipeline:
    # No client retries. The gateway retries rate limits itself, and a spend-cap 429 should end the run.
    llm = OpenAILLM(openai.OpenAI(base_url=base_url, api_key="unused", max_retries=0), model)
    # Attack setup looks up a model name in the pipeline name and fails on unknown ones. "local" maps to
    # AgentDojo's "Local model". DEFAULT_ATTACK discards the result.
    llm.name = f"{model}-local-gateway"
    config = PipelineConfig(llm=llm, model_id=None, defense=defense, system_message_name=None, system_message=None)
    return AgentPipeline.from_config(config)


@cache
def suite(name: str) -> TaskSuite:
    return get_suite(BENCHMARK_VERSION, name)


def run_task(pipeline: AgentPipeline, suite_name: str, user_task: str, logdir: str | Path) -> bool:
    """One user task with no attack. Returns AgentDojo's utility."""
    s = suite(suite_name)
    with OutputLogger(str(logdir)):
        utility, _ = run_task_without_injection_tasks(s, pipeline, s.get_user_task_by_id(user_task), Path(logdir), True, BENCHMARK_VERSION)
    return utility


def run_pair(pipeline: AgentPipeline, suite_name: str, user_task: str, injection_task: str, logdir: str | Path, attack: str = DEFAULT_ATTACK) -> tuple[bool, bool]:
    """One user task with one injection task placed. Returns (utility, security).

    `security` is True when the attack worked. The suite-level functions also run each injection task
    alone. This one doesn't, so each pair can get its own gateway URL key.
    """
    s = suite(suite_name)
    with OutputLogger(str(logdir)):
        utility, security = run_task_with_injection_tasks(
            s, pipeline, s.get_user_task_by_id(user_task), published.make(attack, s, pipeline) or load_attack(attack, s, pipeline), Path(logdir), True,
            injection_tasks=[injection_task], benchmark_version=BENCHMARK_VERSION,
        )
    key = (user_task, injection_task)
    return utility[key], security[key]


def run_benign(pipeline: AgentPipeline, suite_name: str, logdir: str | Path, user_tasks: list[str] | None = None) -> SuiteResults:
    suite = get_suite(BENCHMARK_VERSION, suite_name)
    # AgentDojo's task logger needs an OutputLogger around it, as in its own script.
    with OutputLogger(str(logdir)):
        return benchmark_suite_without_injections(
            pipeline, suite, logdir=Path(logdir), force_rerun=True, user_tasks=user_tasks, benchmark_version=BENCHMARK_VERSION
        )


def run_attacked(
    pipeline: AgentPipeline,
    suite_name: str,
    logdir: str | Path,
    attack: str = DEFAULT_ATTACK,
    user_tasks: list[str] | None = None,
    injection_tasks: list[str] | None = None,
) -> SuiteResults:
    suite = get_suite(BENCHMARK_VERSION, suite_name)
    with OutputLogger(str(logdir)):
        return benchmark_suite_with_injections(
            pipeline,
            suite,
            load_attack(attack, suite, pipeline),
            logdir=Path(logdir),
            force_rerun=True,
            user_tasks=user_tasks,
            injection_tasks=injection_tasks,
            verbose=False,
            benchmark_version=BENCHMARK_VERSION,
        )
