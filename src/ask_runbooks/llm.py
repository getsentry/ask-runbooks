"""
LLM provider abstraction.

Configure in config.yaml:

    llm:
      provider: claude          # or: ollama
      model: claude-sonnet-4-6  # or e.g. llama3.2
      ollama_url: http://localhost:11434  # only for ollama
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from .types import Message


class LLMProvider:
    def ask(self, system: str, messages: list[Message]) -> str:
        raise NotImplementedError


class ClaudeProvider(LLMProvider):
    def __init__(self, model: str) -> None:
        self.model = model

    def ask(self, system: str, messages: list[Message]) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        )
        block = response.content[0]
        assert hasattr(block, "text"), f"Unexpected content block type: {type(block)}"
        return block.text  # type: ignore[union-attr]


class OllamaProvider(LLMProvider):
    def __init__(self, model: str, base_url: str) -> None:
        self.model = model
        self.base_url = base_url

    def ask(self, system: str, messages: list[Message]) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        return data["message"]["content"]


def build_provider(config: dict[str, Any]) -> LLMProvider:
    llm_config = config.get("llm", {})
    provider = llm_config.get("provider", "claude")
    model = llm_config.get("model", "claude-sonnet-4-6")

    if provider == "claude":
        return ClaudeProvider(model)
    elif provider == "ollama":
        base_url = llm_config.get("ollama_url", "http://localhost:11434")
        return OllamaProvider(model, base_url)
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}")
