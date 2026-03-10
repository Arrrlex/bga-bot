import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from bot.llm import (
    AnthropicProvider,
    MoonshotProvider,
    OpenAIProvider,
    get_provider,
)


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns a canned response."""

    def __init__(self, response_data: dict, status_code: int = 200):
        self.response_data = response_data
        self.status_code = status_code
        self.last_request = None

    async def handle_async_request(self, request):
        self.last_request = request
        return httpx.Response(
            status_code=self.status_code,
            json=self.response_data,
            request=request,
        )


@pytest.fixture
def openai_response():
    return {"choices": [{"message": {"content": "test response"}}]}


@pytest.fixture
def anthropic_response():
    return {"content": [{"text": "test response"}]}


def _make_mock_client(transport):
    """Create a patched AsyncClient that uses our mock transport."""
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        real_init(self, *args, **kwargs)

    return patched_init


class TestMoonshotProvider:
    @pytest.mark.asyncio
    async def test_complete_success(self, openai_response):
        transport = MockTransport(openai_response)
        provider = MoonshotProvider(api_key="test-key", model="kimi-k2-5")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            result = await provider.complete("sys prompt", "user prompt")

        assert result == "test response"
        body = json.loads(transport.last_request.content)
        assert body["model"] == "kimi-k2-5"
        assert body["messages"][0] == {"role": "system", "content": "sys prompt"}
        assert body["messages"][1] == {"role": "user", "content": "user prompt"}
        assert transport.last_request.headers["authorization"] == "Bearer test-key"

    @pytest.mark.asyncio
    async def test_complete_error_raises(self):
        transport = MockTransport({"error": "bad"}, status_code=400)
        provider = MoonshotProvider(api_key="test-key")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.complete("sys", "usr")

    @pytest.mark.asyncio
    async def test_url(self, openai_response):
        transport = MockTransport(openai_response)
        provider = MoonshotProvider(api_key="key", model="m")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            await provider.complete("s", "u")

        assert "moonshot.ai" in str(transport.last_request.url)


class TestAnthropicProvider:
    @pytest.mark.asyncio
    async def test_complete_success(self, anthropic_response):
        transport = MockTransport(anthropic_response)
        provider = AnthropicProvider(api_key="ant-key", model="claude-sonnet-4-20250514")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            result = await provider.complete("sys prompt", "user prompt")

        assert result == "test response"
        body = json.loads(transport.last_request.content)
        assert body["model"] == "claude-sonnet-4-20250514"
        assert body["system"] == "sys prompt"
        assert body["messages"] == [{"role": "user", "content": "user prompt"}]
        assert body["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_headers(self, anthropic_response):
        transport = MockTransport(anthropic_response)
        provider = AnthropicProvider(api_key="ant-key")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            await provider.complete("s", "u")

        assert transport.last_request.headers["x-api-key"] == "ant-key"
        assert transport.last_request.headers["anthropic-version"] == "2023-06-01"

    @pytest.mark.asyncio
    async def test_error_raises(self):
        transport = MockTransport({"error": "unauthorized"}, status_code=401)
        provider = AnthropicProvider(api_key="bad")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.complete("s", "u")

    @pytest.mark.asyncio
    async def test_url(self, anthropic_response):
        transport = MockTransport(anthropic_response)
        provider = AnthropicProvider(api_key="k")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            await provider.complete("s", "u")

        assert "anthropic.com" in str(transport.last_request.url)


class TestOpenAIProvider:
    @pytest.mark.asyncio
    async def test_complete_success(self, openai_response):
        transport = MockTransport(openai_response)
        provider = OpenAIProvider(api_key="oai-key", model="gpt-4o")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            result = await provider.complete("sys prompt", "user prompt")

        assert result == "test response"
        body = json.loads(transport.last_request.content)
        assert body["model"] == "gpt-4o"
        assert body["messages"][0] == {"role": "system", "content": "sys prompt"}
        assert body["messages"][1] == {"role": "user", "content": "user prompt"}

    @pytest.mark.asyncio
    async def test_custom_base_url(self, openai_response):
        transport = MockTransport(openai_response)
        provider = OpenAIProvider(api_key="key", model="llama", base_url="https://custom.api.com/v1")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            await provider.complete("s", "u")

        assert "custom.api.com" in str(transport.last_request.url)

    @pytest.mark.asyncio
    async def test_default_base_url(self):
        provider = OpenAIProvider(api_key="key")
        assert provider.base_url == "https://api.openai.com/v1"

    @pytest.mark.asyncio
    async def test_error_raises(self):
        transport = MockTransport({"error": "bad"}, status_code=500)
        provider = OpenAIProvider(api_key="key")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.complete("s", "u")

    @pytest.mark.asyncio
    async def test_empty_choices_raises(self, openai_response):
        transport = MockTransport({"choices": []})
        provider = OpenAIProvider(api_key="key")

        with patch.object(httpx.AsyncClient, "__init__", _make_mock_client(transport)):
            with pytest.raises(IndexError):
                await provider.complete("s", "u")


class TestGetProvider:
    def test_moonshot(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "moonshot")
        monkeypatch.setenv("LLM_API_KEY", "test")
        monkeypatch.setenv("LLM_MODEL", "kimi-k2-5")
        provider = get_provider()
        assert isinstance(provider, MoonshotProvider)
        assert provider.model == "kimi-k2-5"

    def test_anthropic(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_API_KEY", "test")
        monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5-20251001")
        provider = get_provider()
        assert isinstance(provider, AnthropicProvider)
        assert provider.model == "claude-haiku-4-5-20251001"

    def test_openai(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("LLM_API_KEY", "test")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        provider = get_provider()
        assert isinstance(provider, OpenAIProvider)

    def test_unknown_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "unknown")
        monkeypatch.setenv("LLM_API_KEY", "test")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider()

    def test_default_models(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "moonshot")
        monkeypatch.setenv("LLM_API_KEY", "test")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        provider = get_provider()
        assert provider.model == "kimi-k2.5"

    def test_missing_api_key(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "moonshot")
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(KeyError):
            get_provider()
