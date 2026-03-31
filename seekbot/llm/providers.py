from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

import requests


class BaseLLMProvider(ABC):
    name = "base"

    @abstractmethod
    def generate(self, prompt: str, llm_cfg: dict) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_structured(self, prompt: str, llm_cfg: dict, response_model: type) -> Any:
        raise NotImplementedError


def _temperature_kwargs(llm_cfg: dict) -> dict:
    if llm_cfg.get("temperature") is None:
        return {}
    return {"temperature": llm_cfg.get("temperature")}


def _ollama_openai_base_url(llm_cfg: dict) -> str:
    base_url = str(llm_cfg.get("base_url") or "").strip()
    if base_url:
        return base_url.rstrip("/")
    raw_url = str(llm_cfg.get("url") or "").strip()
    if raw_url.endswith("/api/generate"):
        return raw_url[: -len("/api/generate")] + "/v1"
    return "http://localhost:11434/v1"


def _instructor_openai_client(*, api_key: str, base_url: str | None = None):
    try:
        import instructor
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(f"instructor/openai packages not available: {exc}") from exc

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    mode = getattr(getattr(instructor, "Mode", None), "JSON", None)
    return instructor.from_openai(client, mode=mode) if mode is not None else instructor.from_openai(client)


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

    def generate_structured(self, prompt: str, llm_cfg: dict, response_model: type) -> Any:
        client = _instructor_openai_client(
            api_key=llm_cfg.get("api_key") or "ollama",
            base_url=_ollama_openai_base_url(llm_cfg),
        )
        return client.chat.completions.create(
            model=llm_cfg.get("model", "gemma3"),
            messages=[{"role": "user", "content": prompt}],
            response_model=response_model,
            **_temperature_kwargs(llm_cfg),
        )


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

    def generate_structured(self, prompt: str, llm_cfg: dict, response_model: type) -> Any:
        try:
            import instructor
            from openai import OpenAI
        except Exception as exc:
            raise RuntimeError(f"instructor/openai packages not available: {exc}") from exc

        api_key_env = llm_cfg.get("api_key_env") or "OPENAI_API_KEY"
        api_key = llm_cfg.get("api_key") or os.environ.get(api_key_env, "")
        if not api_key:
            raise RuntimeError(f"OpenAI API key not found. Set {api_key_env} or llm.api_key.")

        client_kwargs = {"api_key": api_key}
        if llm_cfg.get("base_url"):
            client_kwargs["base_url"] = llm_cfg["base_url"]
        client = OpenAI(**client_kwargs)
        mode = getattr(getattr(instructor, "Mode", None), "JSON", None)
        patched = instructor.from_openai(client, mode=mode) if mode is not None else instructor.from_openai(client)
        return patched.chat.completions.create(
            model=llm_cfg.get("model", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            response_model=response_model,
            **_temperature_kwargs(llm_cfg),
        )


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

    def generate_structured(self, prompt: str, llm_cfg: dict, response_model: type) -> Any:
        try:
            import anthropic
            import instructor
        except Exception as exc:
            raise RuntimeError(f"instructor/anthropic packages not available: {exc}") from exc

        api_key_env = llm_cfg.get("api_key_env") or "ANTHROPIC_API_KEY"
        api_key = llm_cfg.get("api_key") or os.environ.get(api_key_env, "")
        if not api_key:
            raise RuntimeError(f"Anthropic API key not found. Set {api_key_env} or llm.api_key.")

        client_kwargs = {"api_key": api_key}
        if llm_cfg.get("base_url"):
            client_kwargs["base_url"] = llm_cfg["base_url"]
        client = instructor.from_anthropic(anthropic.Anthropic(**client_kwargs))
        return client.messages.create(
            model=llm_cfg.get("model", "claude-3-5-sonnet-latest"),
            max_tokens=int(llm_cfg.get("anthropic_max_tokens", 1024)),
            messages=[{"role": "user", "content": prompt}],
            response_model=response_model,
            **_temperature_kwargs(llm_cfg),
        )


def create_provider(provider_name: str | None) -> BaseLLMProvider:
    normalized = (provider_name or "").strip().lower()
    providers = {
        "ollama": OllamaHTTPProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
    }
    provider_cls = providers.get(normalized)
    if not provider_cls:
        raise RuntimeError(f"Unsupported LLM provider: {provider_name}")
    return provider_cls()
