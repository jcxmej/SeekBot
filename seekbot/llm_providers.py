from __future__ import annotations

import os
from abc import ABC, abstractmethod

import requests


class BaseLLMProvider(ABC):
    name = "base"

    @abstractmethod
    def generate(self, prompt: str, llm_cfg: dict) -> str:
        raise NotImplementedError


class OllamaClientProvider(BaseLLMProvider):
    name = "ollama_client"

    def generate(self, prompt: str, llm_cfg: dict) -> str:
        try:
            from ollama import generate
        except Exception as exc:
            raise RuntimeError(f"ollama module not available: {exc}") from exc
        response = generate(
            model=llm_cfg.get("model", "llama3.1:8b"),
            prompt=prompt,
            stream=False,
            options={"temperature": llm_cfg.get("temperature", 0.1)},
        )
        if isinstance(response, dict):
            return response.get("response", "")
        return getattr(response, "response", "") or ""


class OllamaHTTPProvider(BaseLLMProvider):
    name = "ollama"

    def generate(self, prompt: str, llm_cfg: dict) -> str:
        payload = {
            "model": llm_cfg.get("model", "llama3.1:8b"),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": llm_cfg.get("temperature", 0.1)},
        }
        response = requests.post(
            llm_cfg.get("url", "http://localhost:11434/api/generate"),
            json=payload,
            timeout=llm_cfg.get("timeout_s", 45),
        )
        response.raise_for_status()
        return response.json().get("response", "")


class OpenAIProvider(BaseLLMProvider):
    name = "openai"

    def generate(self, prompt: str, llm_cfg: dict) -> str:
        try:
            from openai import OpenAI
        except Exception as exc:
            raise RuntimeError(f"openai package not available: {exc}") from exc

        api_key_env = llm_cfg.get("api_key_env") or "OPENAI_API_KEY"
        api_key = llm_cfg.get("api_key") or os.environ.get(api_key_env, "")
        if not api_key:
            raise RuntimeError(f"OpenAI API key not found. Set {api_key_env} or llm.api_key.")

        client_kwargs = {"api_key": api_key}
        if llm_cfg.get("base_url"):
            client_kwargs["base_url"] = llm_cfg["base_url"]
        client = OpenAI(**client_kwargs)

        request_kwargs = {
            "model": llm_cfg.get("model", "gpt-4o-mini"),
            "input": prompt,
        }
        if llm_cfg.get("temperature") is not None:
            request_kwargs["temperature"] = llm_cfg.get("temperature")

        response = client.responses.create(**request_kwargs)
        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text
        return str(response)


class AnthropicProvider(BaseLLMProvider):
    name = "anthropic"

    def generate(self, prompt: str, llm_cfg: dict) -> str:
        try:
            import anthropic
        except Exception as exc:
            raise RuntimeError(f"anthropic package not available: {exc}") from exc

        api_key_env = llm_cfg.get("api_key_env") or "ANTHROPIC_API_KEY"
        api_key = llm_cfg.get("api_key") or os.environ.get(api_key_env, "")
        if not api_key:
            raise RuntimeError(f"Anthropic API key not found. Set {api_key_env} or llm.api_key.")

        client_kwargs = {"api_key": api_key}
        if llm_cfg.get("base_url"):
            client_kwargs["base_url"] = llm_cfg["base_url"]
        client = anthropic.Anthropic(**client_kwargs)

        request_kwargs = {
            "model": llm_cfg.get("model", "claude-3-5-sonnet-latest"),
            "max_tokens": int(llm_cfg.get("anthropic_max_tokens", 1024)),
            "messages": [{"role": "user", "content": prompt}],
        }
        if llm_cfg.get("temperature") is not None:
            request_kwargs["temperature"] = llm_cfg.get("temperature")

        response = client.messages.create(**request_kwargs)
        parts = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", "") == "text":
                parts.append(getattr(block, "text", "") or "")
        return "".join(parts).strip()


def create_provider(provider_name: str | None) -> BaseLLMProvider:
    normalized = (provider_name or "").strip().lower()
    providers = {
        "ollama_client": OllamaClientProvider,
        "ollama": OllamaHTTPProvider,
        "ollama_http": OllamaHTTPProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
    }
    provider_cls = providers.get(normalized)
    if not provider_cls:
        raise RuntimeError(f"Unsupported LLM provider: {provider_name}")
    return provider_cls()
