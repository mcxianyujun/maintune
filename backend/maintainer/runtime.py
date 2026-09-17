import asyncio
import hashlib
import inspect
import json
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol, TypeVar

from pydantic import BaseModel, Field
import httpx

from .providers import Completion, ModelProvider


class AgentRuntime(Protocol):
    async def run(self, provider: ModelProvider, model: str, system: str, prompt: str, timeout: int, parameters: dict | None = None) -> Completion: ...


class DiagnosticRuntime:
    """One bounded call; no tools, secrets API, shell or GitHub mutation authority."""

    async def run(self, provider: ModelProvider, model: str, system: str, prompt: str, timeout: int, parameters: dict | None = None) -> Completion:
        return await model_request(provider_complete(provider, model, system, prompt, timeout, parameters), timeout)


T = TypeVar("T", bound=BaseModel)


async def provider_complete(provider: ModelProvider, model: str, system: str, prompt: str, timeout: int, parameters: dict | None = None) -> Completion:
    """Keep custom providers using the v1 four-argument protocol compatible."""
    signature = inspect.signature(provider.complete)
    accepts_parameters = "parameters" in signature.parameters or any(item.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD) for item in signature.parameters.values())
    if accepts_parameters:
        return await provider.complete(model, system, prompt, timeout, parameters)
    return await provider.complete(model, system, prompt, timeout)


class RuntimeControlError(RuntimeError):
    def __init__(self, message: str, events: list[dict] | None = None):
        super().__init__(message)
        self.events = events or []


class ModelRequestTimeout(RuntimeControlError): pass
class ToolCallTimeout(RuntimeControlError): pass
class AgentTaskTimeout(RuntimeControlError): pass


async def model_request(awaitable, timeout: float):
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except (TimeoutError, httpx.TimeoutException) as error:
        raise ModelRequestTimeout(f"Model request exceeded {timeout} seconds") from error


async def tool_call(awaitable, timeout: float):
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except TimeoutError as error:
        raise ToolCallTimeout(f"Tool call exceeded {timeout} seconds") from error


async def agent_task(awaitable, timeout: float):
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except TimeoutError as error:
        raise AgentTaskTimeout(f"Agent task exceeded {timeout} seconds") from error


def parse_structured(text: str, schema: type[T]) -> T:
    """Accept a JSON object or a single fenced JSON object, never arbitrary prose."""
    value = text.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    return schema.model_validate_json(value)


async def structured_call(provider: ModelProvider, model: str, system: str, prompt: str, schema: type[T], timeout: int, retries: int = 1, parameters: dict | None = None) -> tuple[T, list[Completion]]:
    completions: list[Completion] = []
    request = prompt + "\n\nReturn only JSON matching this schema:\n" + str(schema.model_json_schema())
    for attempt in range(retries + 1):
        completion = await model_request(provider_complete(provider, model, system, request, timeout, parameters), timeout)
        completions.append(completion)
        try:
            return parse_structured(completion.text, schema), completions
        except Exception:
            if attempt >= retries:
                raise ValueError("Model did not return valid structured output") from None
            request += "\nYour previous response was invalid. Return one JSON object only."
    raise AssertionError("unreachable")


@dataclass
class RuntimeResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    budget_events: list[dict] = field(default_factory=list)
    steps_used: int = 0


class AgentLoopDetected(RuntimeControlError): pass


class AgentStepLimitReached(RuntimeControlError): pass
class AgentHardLimitReached(AgentStepLimitReached): pass


@dataclass
class StepBudgetController:
    soft_limit: int
    hard_limit: int
    extension: int = 20
    loop_threshold: int = 3
    current_limit: int = field(init=False)
    steps: int = 0
    fingerprints: list[str] = field(default_factory=list)
    progress: list[bool] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.current_limit = self.soft_limit

    def record(self, tool: str, arguments: dict) -> None:
        fingerprint = hashlib.sha256(json.dumps({"tool": tool, "arguments": arguments}, sort_keys=True, default=str).encode()).hexdigest()
        command = str(arguments.get("command") or "").lower()
        made_progress = tool == "write_file" or (tool == "shell" and any(word in command for word in ("test", "pytest", "npm", "pnpm", "git diff")))
        next_step = self.steps + 1
        repeated = 1
        for previous in reversed(self.fingerprints):
            if previous != fingerprint:
                break
            repeated += 1
        if repeated >= self.loop_threshold:
            self.events.append({"kind": "agent_loop_detected", "step": next_step, "steps_used": self.steps, "repeat_count": repeated, "fingerprint": fingerprint[:16]})
            raise AgentLoopDetected(f"Repeated the same tool action {repeated} times", self.events.copy())
        if next_step > self.hard_limit:
            self.events.append({"kind": "agent_hard_limit_reached", "step": next_step, "steps_used": self.steps, "hard_limit": self.hard_limit})
            raise AgentHardLimitReached(f"Agent reached hard step limit {self.hard_limit}", self.events.copy())
        if next_step > self.current_limit:
            self.events.append({"kind": "agent_soft_limit_reached", "step": next_step, "steps_used": self.steps, "soft_limit": self.current_limit})
            recent_fingerprints = self.fingerprints[-5:]
            progressing = any(self.progress[-5:]) or len(set(recent_fingerprints)) >= 3
            if not progressing or self.current_limit >= self.hard_limit:
                raise AgentStepLimitReached(f"Agent stopped at soft step limit {self.current_limit} without enough progress", self.events.copy())
            old = self.current_limit
            self.current_limit = min(self.current_limit + self.extension, self.hard_limit)
            self.events.append({"kind": "agent_budget_extended", "step": next_step, "steps_used": self.steps, "from": old, "to": self.current_limit})
        self.fingerprints.append(fingerprint)
        self.progress.append(made_progress)
        self.steps = next_step


@lru_cache(maxsize=1)
def sandbox_observation_type():
    """Return a registered concrete observation type required by OpenHands 1.47."""
    from openhands.sdk import Observation

    # OpenHands rejects function-local schema classes during event deserialization.
    # Construct a module-addressable class lazily so importing this module stays light.
    MaintainerSandboxObservation = type(
        "MaintainerSandboxObservation",
        (Observation,),
        {"__module__": __name__},
    )
    globals()["MaintainerSandboxObservation"] = MaintainerSandboxObservation
    return MaintainerSandboxObservation


class OpenHandsRuntime:
    """OpenHands loop with only controller-provided SandboxProvider tools."""

    async def run(self, *, base_url: str, api_key: str, model: str, system: str, prompt: str, sandbox_provider, sandbox_id: str, model_timeout: int, tool_timeout: int, task_timeout: int, soft_step_limit: int, hard_step_limit: int, step_extension: int, loop_threshold: int, parameters: dict | None = None) -> RuntimeResult:
        return await agent_task(
            asyncio.to_thread(
                self._run_sync,
                base_url,
                api_key,
                model,
                system,
                prompt,
                sandbox_provider,
                sandbox_id,
                model_timeout,
                tool_timeout,
                soft_step_limit,
                hard_step_limit,
                step_extension,
                loop_threshold,
                parameters or {},
            ),
            task_timeout,
        )

    @staticmethod
    def _run_sync(base_url, api_key, model, system, prompt, sandbox_provider, sandbox_id, model_timeout, tool_timeout, soft_step_limit, hard_step_limit, step_extension, loop_threshold, parameters):
        from openhands.sdk import Action, Agent, LLM, LocalConversation, Tool, ToolDefinition
        from openhands.sdk.conversation import get_agent_final_response
        from openhands.sdk.tool import ToolExecutor
        from openhands.sdk.tool.registry import register_tool

        calls: list[dict] = []
        budget = StepBudgetController(soft_step_limit, hard_step_limit, step_extension, loop_threshold)
        SandboxObservation = sandbox_observation_type()

        class ShellAction(Action):
            command: str = Field(min_length=1, max_length=4000)
            cwd: str = Field(default=".", max_length=500)
            timeout: int = Field(default=60, ge=1, le=7200)

        class ReadAction(Action):
            path: str = Field(min_length=1, max_length=1000)

        class WriteAction(Action):
            path: str = Field(min_length=1, max_length=1000)
            content: str = Field(max_length=1_000_000)

        class Executor(ToolExecutor):
            def __init__(self, kind): self.kind = kind
            def __call__(self, action, conversation=None):
                safe = action.model_dump(exclude={"content"})
                budget_arguments = action.model_dump()
                if "content" in budget_arguments:
                    budget_arguments["content"] = hashlib.sha256(budget_arguments["content"].encode()).hexdigest()
                budget.record(self.kind, budget_arguments)
                calls.append({"tool": self.kind, "arguments": safe})
                try:
                    if self.kind == "shell":
                        result = asyncio.run(tool_call(sandbox_provider.exec(sandbox_id, action.command, min(action.timeout, tool_timeout), action.cwd), tool_timeout))
                        text = f"exit_code={result['exit_code']}\n{result['output']}"
                    elif self.kind == "read_file":
                        text = asyncio.run(tool_call(sandbox_provider.read_file(sandbox_id, action.path), tool_timeout))
                    else:
                        asyncio.run(tool_call(sandbox_provider.write_file(sandbox_id, action.path, action.content), tool_timeout)); text = "written"
                    return SandboxObservation.from_text(text[:100_000])
                except RuntimeControlError as error:
                    error.events = budget.events.copy() + [{"kind": "agent_tool_timeout", "steps_used": budget.steps, "tool": self.kind, "timeout": tool_timeout}] if isinstance(error, ToolCallTimeout) else budget.events.copy()
                    raise
                except Exception as error:
                    return SandboxObservation.from_text(type(error).__name__ + ": tool failed", is_error=True)

        class ShellTool(ToolDefinition[ShellAction, SandboxObservation]):
            @classmethod
            def create(cls, conv_state, **params): return [cls(description="Execute a shell command inside the assigned sandbox workspace.", action_type=ShellAction, observation_type=SandboxObservation, executor=Executor("shell"))]
        class ReadTool(ToolDefinition[ReadAction, SandboxObservation]):
            @classmethod
            def create(cls, conv_state, **params): return [cls(description="Read a UTF-8 file relative to the assigned sandbox workspace.", action_type=ReadAction, observation_type=SandboxObservation, executor=Executor("read_file"))]
        class WriteTool(ToolDefinition[WriteAction, SandboxObservation]):
            @classmethod
            def create(cls, conv_state, **params): return [cls(description="Write a UTF-8 file relative to the assigned sandbox workspace.", action_type=WriteAction, observation_type=SandboxObservation, executor=Executor("write_file"))]
        suffix = hashlib.sha256(f"{sandbox_id}:{id(sandbox_provider)}".encode()).hexdigest()[:12]
        ShellTool.name = f"maintainer_shell_{suffix}"
        ReadTool.name = f"maintainer_read_{suffix}"
        WriteTool.name = f"maintainer_write_{suffix}"
        register_tool(ShellTool.name, ShellTool)
        register_tool(ReadTool.name, ReadTool)
        register_tool(WriteTool.name, WriteTool)
        tools = [Tool(name=ShellTool.name), Tool(name=ReadTool.name), Tool(name=WriteTool.name)]
        llm_parameters = dict(parameters)
        temperature = llm_parameters.pop("temperature", None)
        top_p = llm_parameters.pop("top_p", None)
        max_output_tokens = llm_parameters.pop("max_tokens", None)
        reasoning_effort = llm_parameters.pop("reasoning_effort", None)
        reasoning_budget = llm_parameters.pop("reasoning_budget", None)
        if reasoning_budget == "auto":
            reasoning_budget = None
        llm = LLM(
            model="openai/" + model,
            api_key=api_key,
            base_url=base_url,
            timeout=model_timeout,
            num_retries=2,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            extended_thinking_budget=reasoning_budget if isinstance(reasoning_budget, int) else None,
            enable_encrypted_reasoning=False,
            litellm_extra_body=llm_parameters,
            usage_id="worker",
        )
        agent = Agent(llm=llm, tools=tools, system_prompt=system)
        with tempfile.TemporaryDirectory(prefix="maintainer-openhands-") as runtime_dir:
            conversation = LocalConversation(agent=agent, workspace=runtime_dir, persistence_dir=None, profile_store_dir=runtime_dir, max_iteration_per_run=hard_step_limit, stuck_detection=True, visualizer=None, delete_on_close=True)
            try:
                conversation.send_message(prompt)
                conversation.run()
                text = get_agent_final_response(list(conversation.state.events))
                metrics = conversation.conversation_stats.get_combined_metrics().accumulated_token_usage
                incoming = int(getattr(metrics, "prompt_tokens", 0) or 0)
                outgoing = int(getattr(metrics, "completion_tokens", 0) or 0)
                return RuntimeResult(text=text, input_tokens=incoming, output_tokens=outgoing, total_tokens=incoming + outgoing, tool_calls=calls, budget_events=budget.events, steps_used=budget.steps)
            finally:
                conversation.close()
