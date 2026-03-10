import os
from abc import ABC, abstractmethod

import httpx


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, system: str, user: str) -> str: ...


class MoonshotProvider(LLMProvider):
    """Kimi k2.5 via Moonshot API."""

    def __init__(self, api_key: str, model: str = "kimi-k2.5"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.moonshot.ai/v1"

    async def complete(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "max_tokens": 8192,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""
            if reasoning:
                return f"<reasoning>\n{reasoning}\n</reasoning>\n\n{content}"
            return content


class AnthropicProvider(LLMProvider):
    """Claude via Anthropic API."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.anthropic.com/v1"

    async def complete(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 4096,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible endpoint."""

    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: str | None = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"

    async def complete(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]


def get_provider() -> LLMProvider:
    """Instantiate provider from environment variables."""
    provider_name = os.environ.get("LLM_PROVIDER", "moonshot")
    api_key = os.environ["LLM_API_KEY"]
    model = os.environ.get("LLM_MODEL", "")

    match provider_name:
        case "moonshot":
            return MoonshotProvider(api_key, model or "kimi-k2.5")
        case "anthropic":
            return AnthropicProvider(api_key, model or "claude-sonnet-4-20250514")
        case "openai":
            return OpenAIProvider(
                api_key,
                model or "gpt-4o",
                os.environ.get("LLM_BASE_URL"),
            )
        case _:
            raise ValueError(f"Unknown LLM provider: {provider_name}")
