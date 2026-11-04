"""Tiny LLM provider layer: OpenAI-compatible, Anthropic, and a mock.

Standard library only (urllib). The LLM is *optional*: the agent answers from
the knowledge base, books appointments and hands off to staff without it. When
configured, it is used only as a grounded fallback for questions the FAQ search
cannot match confidently, and it must answer from the supplied facts or say
UNKNOWN (which triggers the normal "I didn't understand / talk to staff" path).

Environment variables
---------------------
WA_LLM_PROVIDER   mock | openai | openrouter | groq | ollama | lmstudio | anthropic   (default: mock)
WA_LLM_MODEL      model name for the chosen provider
WA_LLM_BASE_URL   override the OpenAI-compatible base URL
WA_LLM_API_KEY / OPENAI_API_KEY   key for OpenAI-compatible endpoints
ANTHROPIC_API_KEY key for Anthropic
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

UNKNOWN = "UNKNOWN"


class ProviderError(RuntimeError):
    pass


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


class LLM(Protocol):
    name: str
    model: str

    def complete(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 400) -> str: ...


def _post(url: str, payload: dict, headers: dict[str, str], timeout: float = 30.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code} from {url}: {e.read().decode('utf-8', 'replace')[:400]}") from e
    except urllib.error.URLError as e:
        raise ProviderError(f"Cannot reach {url}: {e.reason}") from e


class OpenAICompatible:
    """OpenAI, OpenRouter, Groq, Ollama (/v1), LM Studio, vLLM, ..."""

    name = "openai"

    def __init__(self, model: str, api_key: str | None, base_url: str = "https://api.openai.com/v1"):
        self.model, self.api_key, self.base_url = model, api_key, base_url.rstrip("/")

    def complete(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 400) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _post(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            headers,
        )
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected response: {str(data)[:300]}") from e


class Anthropic:
    name = "anthropic"

    def __init__(self, model: str, api_key: str | None, base_url: str = "https://api.anthropic.com"):
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        self.model, self.api_key, self.base_url = model, api_key, base_url.rstrip("/")

    def complete(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 400) -> str:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages if m.role != "system"],
        }
        if system:
            payload["system"] = system
        data = _post(
            f"{self.base_url}/v1/messages", payload, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        )
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise ProviderError(f"Unexpected response: {str(data)[:300]}") from e


class Mock:
    """Offline stand-in. It does not generate language: it always answers UNKNOWN,
    so the agent falls back to its deterministic paths (menu, then staff handoff).
    Tests and the demo use it; nothing it 'says' is presented as model output."""

    name = "mock"

    def __init__(self, model: str = "none"):
        self.model = model
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 400) -> str:
        self.calls.append(messages)
        return UNKNOWN


OPENAI_COMPATIBLE = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
}


def get_llm(provider: str | None = None, model: str | None = None) -> LLM:
    provider = (provider or os.getenv("WA_LLM_PROVIDER") or "mock").lower()
    model = model or os.getenv("WA_LLM_MODEL") or None
    if provider == "mock":
        return Mock()
    if provider in OPENAI_COMPATIBLE or provider == "openai-compatible":
        base = os.getenv("WA_LLM_BASE_URL") or OPENAI_COMPATIBLE.get(provider, OPENAI_COMPATIBLE["openai"])
        key = os.getenv("WA_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        local = provider in {"ollama", "lmstudio"} or "localhost" in base or "127.0.0.1" in base
        if not key and not local:
            raise ProviderError(f"Set WA_LLM_API_KEY (or OPENAI_API_KEY) for provider {provider!r}")
        return OpenAICompatible(model or "gpt-4o-mini", key, base)
    if provider == "anthropic":
        return Anthropic(model or "claude-sonnet-4-5", os.getenv("ANTHROPIC_API_KEY"))
    raise ProviderError(
        f"Unknown provider {provider!r}; use mock, openai, openrouter, groq, ollama, lmstudio or anthropic"
    )
