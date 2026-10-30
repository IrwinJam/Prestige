"""Run AgentDojo through the gateway.

AgentDojo is used as a library, not through its benchmark script. Its released version (0.1.35) has no
setting for an arbitrary OpenAI-compatible URL, but its pipeline accepts a model object, so it gets an
OpenAI client pointed at the gateway. Every model call then goes through the gateway and into its trace
database, and AgentDojo's own tool calling and defenses stay exactly as published.

Its logs go under `runs/`, which is never committed. They hold the benchmark's injected text.
"""

from __future__ import annotations

from pathlib import Path

import openai
from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import SuiteResults, benchmark_suite_with_injections, benchmark_suite_without_injections
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite

BENCHMARK_VERSION = "v1.2.2"
# The standard attack names the target model, and AgentDojo only knows OpenAI, Anthropic and Google
# model names. This published variant leaves the name out, so nothing about Muse gets made up.
DEFAULT_ATTACK = "important_instructions_no_model_name"


def build_pipeline(base_url: str, model: str, defense: str | None = None) -> AgentPipeline:
    # No client retries: the gateway already retries rate limits, and a spend-cap 429 should stop the run.
    llm = OpenAILLM(openai.OpenAI(base_url=base_url, api_key="unused", max_retries=0), model)
    # Attacks look up a model name from the pipeline name and fail on names they don't know. "local" maps
    # to AgentDojo's own "Local model" label. DEFAULT_ATTACK discards the lookup anyway.
    llm.name = f"{model}-local-gateway"
    config = PipelineConfig(llm=llm, model_id=None, defense=defense, system_message_name=None, system_message=None)
    return AgentPipeline.from_config(config)


def run_benign(pipeline: AgentPipeline, suite_name: str, logdir: str | Path, user_tasks: list[str] | None = None) -> SuiteResults:
    suite = get_suite(BENCHMARK_VERSION, suite_name)
    # AgentDojo's per-task logger only works inside an OutputLogger, the way its own script runs it.
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
