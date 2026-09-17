from .schemas import (
    AgentInput,
    AgentRuntimeOverride,
    GeneralSettings,
    GenerationConfig,
    ModelCapabilities,
    ModelDefaults,
    ModelDefinition,
    ReasoningConfig,
    ReasoningOverride,
    StepConfig,
    TimeoutConfig,
    TimeoutOverride,
)


def reset_model(definition: ModelDefinition, scope: str) -> ModelDefinition:
    if scope == "all":
        return definition.model_copy(update={"defaults": ModelDefaults()})
    defaults = definition.defaults.model_copy(deep=True)
    if scope == "reasoning": defaults.reasoning = ReasoningConfig()
    elif scope == "generation": defaults.generation = GenerationConfig()
    elif scope == "budget": defaults.reasoning.budget = None
    elif scope == "timeouts": defaults.request_timeout = None
    elif scope == "extra_params": defaults.extra_params = {}
    elif scope == "advanced":
        defaults.request_timeout = None
        defaults.extra_params = {}
    elif scope == "capabilities": return definition.model_copy(update={"capabilities": ModelCapabilities()})
    else: raise ValueError("Reset scope is not valid for a model")
    return definition.model_copy(update={"defaults": defaults})


def reset_main(settings: GeneralSettings, scope: str) -> GeneralSettings:
    updates = {}
    if scope in {"reasoning", "all"}: updates["reasoning"] = ReasoningOverride()
    if scope in {"generation", "all"}: updates["generation"] = GenerationConfig()
    if scope in {"steps", "budget", "all"}: updates["steps"] = StepConfig()
    if scope in {"timeouts", "all"}: updates["timeouts"] = TimeoutConfig()
    if not updates: raise ValueError("Reset scope is not valid for the main agent")
    return settings.model_copy(update=updates)


def reset_agent(agent: AgentInput, scope: str) -> AgentInput:
    runtime = agent.runtime.model_copy(deep=True)
    updates = {}
    if scope == "all":
        return agent.model_copy(update={"model": None, "runtime": AgentRuntimeOverride()})
    if scope == "reasoning": runtime.reasoning = ReasoningOverride()
    elif scope == "generation": runtime.generation = GenerationConfig()
    elif scope in {"steps", "budget"}: runtime.steps = None
    elif scope == "timeouts": runtime.timeouts = TimeoutOverride()
    else: raise ValueError("Reset scope is not valid for a sub agent")
    updates["runtime"] = runtime
    return agent.model_copy(update=updates)
