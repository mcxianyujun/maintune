from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from .db import Agent, Config, Provider
from .schemas import AgentInput, GeneralSettings, ModelDefinition, ProviderInput


AUTO_STEP_LIMITS: dict[str, tuple[int, int]] = {
    "issue_analyzer": (20, 40),
    "ci_analyzer": (30, 60),
    "pr_reviewer": (50, 100),
    "code_reviewer": (50, 100),
    "code_worker": (100, 200),
    "main": (60, 120),
}


class ResolvedAgentConfig(BaseModel):
    agent: str
    provider: str
    provider_name: str
    provider_type: str
    base_url: str
    model: str
    model_display_name: str
    system_prompt: str
    capabilities: dict[str, bool]
    reasoning_mode: str
    reasoning_effort: str
    reasoning_budget: int | str | None
    temperature: float | None
    top_p: float | None
    max_output_tokens: int | None
    extra_params: dict[str, Any]
    steps_mode: str
    soft_step_limit: int
    hard_step_limit: int
    step_extension: int
    loop_threshold: int
    model_timeout: int
    tool_timeout: int
    task_timeout: int
    sandbox_ttl: int

    def audit_snapshot(self) -> dict[str, Any]:
        return self.model_dump(exclude={"system_prompt", "base_url", "extra_params"})


def _overlay(base: dict[str, Any], override: BaseModel) -> dict[str, Any]:
    for key, value in override.model_dump().items():
        if value is not None and value != "inherit":
            base[key] = value
    return base


def _model(provider: ProviderInput, model_id: str) -> ModelDefinition:
    for definition in provider.models:
        if definition.id == model_id and definition.enabled:
            return definition
    raise ValueError("Referenced model is unavailable")


def resolve_agent_config(db, agent_id: str) -> ResolvedAgentConfig:
    general = GeneralSettings.model_validate(db.get(Config, "general").data)
    if not general.model:
        raise ValueError("Main model is not configured")
    agent = None
    ref, system = general.model, general.system_prompt
    if agent_id != "main":
        row = db.get(Agent, agent_id)
        if not row:
            raise ValueError(f"Agent {agent_id} is unavailable")
        agent = AgentInput.model_validate(row.data)
        if not agent.enabled:
            raise ValueError(f"Agent {agent_id} is unavailable")
        ref, system = agent.model or ref, agent.system_prompt
    provider_row = db.get(Provider, ref.provider)
    if not provider_row:
        raise ValueError("Referenced provider is unavailable")
    provider = ProviderInput.model_validate(provider_row.data)
    definition = _model(provider, ref.model)

    reasoning = definition.defaults.reasoning.model_dump()
    _overlay(reasoning, general.reasoning)
    generation = definition.defaults.generation.model_dump()
    _overlay(generation, general.generation)
    if agent:
        _overlay(reasoning, agent.runtime.reasoning)
        _overlay(generation, agent.runtime.generation)
    if reasoning["budget"] == "unset":
        reasoning["budget"] = None

    steps = agent.runtime.steps if agent and agent.runtime.steps is not None else general.steps
    if steps.mode == "auto":
        soft, hard = AUTO_STEP_LIMITS.get(agent_id, AUTO_STEP_LIMITS["main"])
        soft, hard = steps.soft_limit or soft, steps.hard_limit or hard
    else:
        soft = steps.soft_limit or steps.fixed_steps or 1
        hard = steps.hard_limit or steps.fixed_steps or soft

    model_timeout = general.timeouts.model_request or definition.defaults.request_timeout or 300
    tool_timeout = general.timeouts.tool_call or 600
    task_timeout = general.timeouts.agent_task or 1800
    sandbox_ttl = general.timeouts.sandbox_ttl or 3600
    if agent:
        timeout_override = agent.runtime.timeouts
        model_timeout = timeout_override.model_request or model_timeout
        tool_timeout = timeout_override.tool_call or tool_timeout
        task_timeout = timeout_override.agent_task or task_timeout
        sandbox_ttl = timeout_override.sandbox_ttl or sandbox_ttl

    return ResolvedAgentConfig(
        agent=agent_id,
        provider=ref.provider,
        provider_name=provider.name,
        provider_type=provider.type,
        base_url=provider.base_url,
        model=definition.id,
        model_display_name=definition.display_name or definition.id,
        system_prompt=system,
        capabilities=definition.capabilities.model_dump(),
        reasoning_mode=reasoning["mode"],
        reasoning_effort=reasoning["effort"],
        reasoning_budget=reasoning["budget"],
        temperature=generation["temperature"],
        top_p=generation["top_p"],
        max_output_tokens=generation["max_output_tokens"],
        extra_params=deepcopy(definition.defaults.extra_params),
        steps_mode=steps.mode,
        soft_step_limit=soft,
        hard_step_limit=hard,
        step_extension=steps.extension,
        loop_threshold=steps.loop_threshold,
        model_timeout=model_timeout,
        tool_timeout=tool_timeout,
        task_timeout=task_timeout,
        sandbox_ttl=sandbox_ttl,
    )


def resolve_all_agents(db) -> dict[str, ResolvedAgentConfig]:
    identifiers = ["main"] + [row.id for row in db.query(Agent).order_by(Agent.id)]
    resolved: dict[str, ResolvedAgentConfig] = {}
    for identifier in identifiers:
        try:
            resolved[identifier] = resolve_agent_config(db, identifier)
        except ValueError:
            continue
    return resolved
