from copy import deepcopy
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .config import ResolvedAgentConfig


class Completion(BaseModel):
    text: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    usage_reported: bool = False


class ModelProvider(Protocol):
    async def complete(self, model: str, system: str, prompt: str, timeout: int, parameters: dict[str, Any] | None = None) -> Completion: ...


class OpenAICompatible:
    def __init__(self, base_url: str, key: str):
        self.base_url, self.key = base_url, key

    def client(self, timeout: int = 15) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url + "/", headers={"Authorization": f"Bearer {self.key}"}, timeout=timeout, follow_redirects=False, trust_env=False)

    async def models(self) -> list[str]:
        async with self.client() as client:
            response = await client.get("models")
            response.raise_for_status()
            return [item["id"] for item in response.json()["data"]][:100]

    async def complete(self, model: str, system: str, prompt: str, timeout: int, parameters: dict[str, Any] | None = None) -> Completion:
        async with self.client(timeout) as client:
            payload = dict(parameters or {})
            # Controller-owned identity and messages always take precedence over
            # extensible model parameters.
            payload.update({"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
            response = await client.post("chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            usage = body.get("usage") or {}
            incoming, outgoing = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            completion_details = usage.get("completion_tokens_details") or {}
            prompt_details = usage.get("prompt_tokens_details") or {}
            return Completion(
                text=body["choices"][0]["message"]["content"],
                input_tokens=incoming,
                output_tokens=outgoing,
                total_tokens=usage.get("total_tokens", incoming + outgoing),
                reasoning_tokens=completion_details.get("reasoning_tokens", 0) or 0,
                cached_tokens=prompt_details.get("cached_tokens", 0) or 0,
                usage_reported=bool(usage),
            )


def openai_compatible_parameters(config: "ResolvedAgentConfig") -> dict[str, Any]:
    """Provider adapter: capability-gate standard fields; standard fields win."""
    parameters = deepcopy(getattr(config, "extra_params", {}) or {})
    for reserved in {
        "model", "messages", "reasoning", "reasoning_effort", "reasoning_budget",
        "temperature", "top_p", "max_tokens", "max_output_tokens", "timeout",
    }:
        parameters.pop(reserved, None)
    capabilities = getattr(config, "capabilities", None)
    if capabilities is None:
        return parameters
    if capabilities.get("supports_reasoning"):
        if config.reasoning_mode == "on":
            parameters["reasoning"] = {"enabled": True}
        elif config.reasoning_mode == "off":
            parameters["reasoning"] = {"enabled": False}
    if capabilities.get("supports_reasoning_effort") and config.reasoning_effort != "inherit":
        parameters["reasoning_effort"] = "xhigh" if config.reasoning_effort == "extra_high" else config.reasoning_effort
    if capabilities.get("supports_reasoning_budget") and config.reasoning_budget is not None:
        parameters["reasoning_budget"] = config.reasoning_budget
    if capabilities.get("supports_temperature") and config.temperature is not None:
        parameters["temperature"] = config.temperature
    if capabilities.get("supports_top_p") and config.top_p is not None:
        parameters["top_p"] = config.top_p
    if capabilities.get("supports_max_output_tokens") and config.max_output_tokens is not None:
        parameters["max_tokens"] = config.max_output_tokens
    return parameters
