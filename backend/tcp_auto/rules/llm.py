"""Provider-neutral LLM access for the rules assistant.

FlagPole only needs one capability from a language model: "given these instructions and this
text, return JSON matching this schema". Each provider adapter implements ``generate_json``.

Providers
- ``anthropic``          Anthropic Claude API (official SDK).
- ``openai_compatible``  Any server that speaks the OpenAI Chat Completions API: OpenAI, Google
                         Gemini (OpenAI endpoint), Mistral, Groq, OpenRouter, Together, and
                         self-hosted/on-prem servers like Ollama, vLLM, LM Studio, or a LiteLLM
                         gateway (which can front AWS Bedrock, Vertex AI, and others).
- ``azure_openai``       Azure OpenAI deployments (deployment + api-version URL scheme).

Configuration comes from the app's AI settings (``<data>/settings.json``) or environment
variables, which win when set:
    TCP_LLM_PROVIDER, TCP_LLM_MODEL, TCP_LLM_BASE_URL, TCP_LLM_API_KEY,
    TCP_LLM_API_VERSION, TCP_LLM_DEPLOYMENT, TCP_LLM_JSON_MODE, TCP_LLM_TIMEOUT
    (ANTHROPIC_API_KEY / OPENAI_API_KEY / AZURE_OPENAI_API_KEY also work for the matching provider.)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Optional, Protocol

import httpx
from pydantic import BaseModel

Provider = Literal["anthropic", "openai_compatible", "azure_openai"]
JsonMode = Literal["auto", "json_schema", "json_object", "prompt"]

DEFAULT_MODELS = {"anthropic": "claude-opus-5-5"}

# Suggested endpoints shown in the settings screen (users can type any URL).
PRESETS = [
    {"id": "anthropic", "label": "Anthropic (Claude)", "provider": "anthropic", "base_url": "", "model": "claude-opus-5-5", "needs_key": True},
    {"id": "openai", "label": "OpenAI", "provider": "openai_compatible", "base_url": "https://api.openai.com/v1", "model": "", "needs_key": True},
    {"id": "azure", "label": "Azure OpenAI", "provider": "azure_openai", "base_url": "https://YOUR-RESOURCE.openai.azure.com", "model": "", "needs_key": True},
    {"id": "gemini", "label": "Google Gemini", "provider": "openai_compatible", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "", "needs_key": True},
    {"id": "mistral", "label": "Mistral", "provider": "openai_compatible", "base_url": "https://api.mistral.ai/v1", "model": "", "needs_key": True},
    {"id": "groq", "label": "Groq", "provider": "openai_compatible", "base_url": "https://api.groq.com/openai/v1", "model": "", "needs_key": True},
    {"id": "openrouter", "label": "OpenRouter", "provider": "openai_compatible", "base_url": "https://openrouter.ai/api/v1", "model": "", "needs_key": True},
    {"id": "ollama", "label": "Ollama (local / on-prem)", "provider": "openai_compatible", "base_url": "http://localhost:11434/v1", "model": "", "needs_key": False},
    {"id": "lmstudio", "label": "LM Studio (local)", "provider": "openai_compatible", "base_url": "http://localhost:1234/v1", "model": "", "needs_key": False},
    {"id": "vllm", "label": "vLLM / LiteLLM gateway / other OpenAI-compatible", "provider": "openai_compatible", "base_url": "http://localhost:8000/v1", "model": "", "needs_key": False},
]


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class LLMConfig(BaseModel):
    provider: Provider = "anthropic"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    api_version: str = "2024-10-21"  # Azure OpenAI
    deployment: str = ""  # Azure OpenAI (defaults to model)
    json_mode: JsonMode = "auto"
    timeout: float = 180.0
    max_output_tokens: int = 0  # 0 = provider default (16000 Anthropic, 8192 others)
    extra_headers: dict[str, str] = {}

    def output_tokens(self) -> int:
        return self.max_output_tokens or (16000 if self.provider == "anthropic" else 8192)

    def effective_model(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.provider, "")

    def public(self) -> dict:
        """Safe to send to the browser (no key)."""
        d = self.model_dump(exclude={"api_key", "extra_headers"})
        d["model"] = self.effective_model()
        d["key_hint"] = f"…{self.api_key[-4:]}" if self.api_key else None
        d["extra_header_names"] = sorted(self.extra_headers)
        return d


class JsonGenerator(Protocol):
    def generate_json(self, system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict: ...


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def parse_json_loose(text: str) -> Any:
    """Parse model output that should be JSON, tolerating code fences or surrounding prose."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError("The AI returned an answer that isn't valid JSON. Try again, or use a model that supports JSON output.", 502)


def schema_instructions(schema: dict) -> str:
    return (
        "Respond with ONLY a JSON object (no prose, no code fences) that matches this JSON Schema exactly:\n"
        + json.dumps(schema)
    )


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class AnthropicGenerator:
    def __init__(self, cfg: LLMConfig, client: Any = None):
        self.cfg = cfg
        self.client = client

    def _client(self):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise LLMError("The 'anthropic' package isn't installed on the server.", 500) from e
        if not self.cfg.api_key:
            raise LLMError("No API key configured for Anthropic.", 400)
        kw: dict[str, Any] = {"api_key": self.cfg.api_key, "timeout": self.cfg.timeout}
        if self.cfg.base_url:
            kw["base_url"] = self.cfg.base_url  # e.g. a company gateway in front of the Claude API
        if self.cfg.extra_headers:
            kw["default_headers"] = self.cfg.extra_headers
        return anthropic.Anthropic(**kw)

    def generate_json(self, system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict:
        import anthropic

        client = self.client or self._client()
        try:
            response = client.beta.messages.create(
                model=self.cfg.effective_model(),
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise LLMError("The API key was rejected. Check it in AI settings.", 400) from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError("The API key doesn't have access to this model.", 400) from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Model '{self.cfg.effective_model()}' wasn't found.", 400) from e
        except anthropic.RateLimitError as e:
            raise LLMError("The AI service is rate-limiting requests. Try again in a minute.", 429) from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"The AI service rejected the request: {e.message}", 400) from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"AI service error ({e.status_code}). Try again later.", 502) from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Couldn't reach the AI service. Check the server's network or proxy settings.", 503) from e
        if response.stop_reason == "refusal":
            raise LLMError("The AI declined to process this text. You can enter the rule manually instead.", 422)
        if response.stop_reason == "max_tokens":
            raise LLMError("The text was too long to convert in one pass. Paste one section at a time.", 413)
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        return parse_json_loose(text)


# ---------------------------------------------------------------------------
# OpenAI-compatible (and Azure OpenAI)
# ---------------------------------------------------------------------------


class OpenAICompatibleGenerator:
    """Chat Completions over plain HTTP, so any compatible server works without extra SDKs.

    JSON output: ``auto`` tries strict JSON Schema output, then JSON mode, then schema-in-prompt,
    falling back when a server rejects the option (many local servers support only some modes).
    """

    def __init__(self, cfg: LLMConfig, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.transport = transport

    # URL / headers --------------------------------------------------------------
    def _url(self) -> str:
        base = self.cfg.base_url.rstrip("/")
        if not base:
            raise LLMError("Set the endpoint URL (base URL) in AI settings.", 400)
        if self.cfg.provider == "azure_openai":
            dep = self.cfg.deployment or self.cfg.model
            if not dep:
                raise LLMError("Set the Azure OpenAI deployment name in AI settings.", 400)
            return f"{base}/openai/deployments/{dep}/chat/completions?api-version={self.cfg.api_version}"
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            if self.cfg.provider == "azure_openai":
                h["api-key"] = self.cfg.api_key
            else:
                h["Authorization"] = f"Bearer {self.cfg.api_key}"
        h.update(self.cfg.extra_headers)
        return h

    # request ----------------------------------------------------------------------
    def _post(self, body: dict) -> httpx.Response:
        try:
            with httpx.Client(timeout=self.cfg.timeout, transport=self.transport) as c:
                return c.post(self._url(), headers=self._headers(), json=body)
        except httpx.TimeoutException as e:
            raise LLMError("The AI service took too long to answer. Try a shorter section or a faster model.", 504) from e
        except httpx.HTTPError as e:
            raise LLMError(f"Couldn't reach the AI service at {self.cfg.base_url}: {e.__class__.__name__}. Check the URL and network/proxy.", 503) from e

    def _body(self, system: str, user: str, schema: dict, mode: str, max_tokens: int) -> dict:
        sys_text = system if mode == "json_schema" else system + "\n\n" + schema_instructions(schema)
        body: dict[str, Any] = {"messages": [{"role": "system", "content": sys_text}, {"role": "user", "content": user}], "max_tokens": max_tokens}
        if self.cfg.provider != "azure_openai":
            if not self.cfg.model:
                raise LLMError("Set the model name in AI settings (as your provider spells it).", 400)
            body["model"] = self.cfg.model
        if mode == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "flagpole_rules", "strict": True, "schema": schema}}
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    def generate_json(self, system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict:
        all_modes = ["json_schema", "json_object", "prompt"]
        key = (self.cfg.provider, self.cfg.base_url.rstrip("/"), self.cfg.deployment or self.cfg.model)
        if self.cfg.json_mode == "auto":
            known = _MODE_CACHE.get(key)  # skip modes this server already rejected
            modes = all_modes[all_modes.index(known):] if known else all_modes
        else:
            modes = [self.cfg.json_mode]
        last_error = ""
        for mode in modes:
            r = self._post(self._body(system, user, schema, mode, max_tokens))
            if r.status_code == 400 and len(modes) > 1 and mode != "prompt" and _format_unsupported(r):
                last_error = _error_text(r)
                continue  # server doesn't support this output mode; try the next one
            if r.status_code == 400 and "max_tokens" in _error_text(r) and "max_completion_tokens" in _error_text(r):
                body = self._body(system, user, schema, mode, max_tokens)
                body["max_completion_tokens"] = body.pop("max_tokens")
                r = self._post(body)
            _raise_for_status(r)
            if self.cfg.json_mode == "auto":
                _MODE_CACHE[key] = mode
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            if msg.get("refusal") or choice.get("finish_reason") == "content_filter":
                raise LLMError("The AI declined to process this text (content filter). You can enter the rule manually instead.", 422)
            if choice.get("finish_reason") == "length":
                raise LLMError("The answer was cut off. Paste a shorter section or raise the model's output limit.", 413)
            content = msg.get("content")
            if isinstance(content, list):  # some servers return content parts
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            return parse_json_loose(content or "")
        raise LLMError(f"The AI service didn't accept any JSON output mode: {last_error}", 400)


_MODE_CACHE: dict[tuple, str] = {}


def _error_text(r: httpx.Response) -> str:
    try:
        j = r.json()
        err = j.get("error", j)
        return json.dumps(err) if not isinstance(err, str) else err
    except Exception:
        return r.text[:500]


def _format_unsupported(r: httpx.Response) -> bool:
    t = _error_text(r).lower()
    return any(s in t for s in ("response_format", "json_schema", "json_object", "structured output", "not supported", "unsupported", "unknown field"))


def _raise_for_status(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    detail = _error_text(r)[:300]
    if r.status_code in (401, 403):
        raise LLMError(f"The AI service rejected the credentials ({r.status_code}). Check the API key in AI settings.", 400)
    if r.status_code == 404:
        raise LLMError(f"Endpoint or model not found (404). Check the base URL and model/deployment name. {detail}", 400)
    if r.status_code == 429:
        raise LLMError("The AI service is rate-limiting requests. Try again in a minute.", 429)
    if r.status_code >= 500:
        raise LLMError(f"AI service error ({r.status_code}). Try again later.", 502)
    raise LLMError(f"The AI service rejected the request ({r.status_code}): {detail}", 400)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def generator_for(cfg: LLMConfig, **kw) -> JsonGenerator:
    if cfg.provider == "anthropic":
        return AnthropicGenerator(cfg, client=kw.get("client"))
    return OpenAICompatibleGenerator(cfg, transport=kw.get("transport"))


def config_from(settings: dict) -> tuple[LLMConfig, dict[str, str]]:
    """Merge saved settings with environment variables. Returns the config and where each value came from."""
    s = dict(settings.get("llm") or {})
    # settings written by earlier versions
    if not s and settings.get("anthropic_api_key"):
        s = {"provider": "anthropic", "api_key": settings["anthropic_api_key"], "model": settings.get("model", "")}
    src: dict[str, str] = {k: "app settings" for k, v in s.items() if v}
    env_map = {"provider": "TCP_LLM_PROVIDER", "model": "TCP_LLM_MODEL", "base_url": "TCP_LLM_BASE_URL", "api_key": "TCP_LLM_API_KEY",
               "api_version": "TCP_LLM_API_VERSION", "deployment": "TCP_LLM_DEPLOYMENT", "json_mode": "TCP_LLM_JSON_MODE", "timeout": "TCP_LLM_TIMEOUT",
               "max_output_tokens": "TCP_LLM_MAX_OUTPUT_TOKENS"}
    for field, var in env_map.items():
        if os.environ.get(var):
            s[field] = os.environ[var]
            src[field] = "environment"
    provider = s.get("provider") or "anthropic"
    if not s.get("api_key"):
        fallback = {"anthropic": "ANTHROPIC_API_KEY", "openai_compatible": "OPENAI_API_KEY", "azure_openai": "AZURE_OPENAI_API_KEY"}.get(provider)
        if fallback and os.environ.get(fallback):
            s["api_key"] = os.environ[fallback]
            src["api_key"] = "environment"
    if provider == "azure_openai" and not s.get("base_url") and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        s["base_url"] = os.environ["AZURE_OPENAI_ENDPOINT"]
        src["base_url"] = "environment"
    try:
        cfg = LLMConfig(**{k: v for k, v in s.items() if v not in (None, "")})
    except Exception as e:
        raise LLMError(f"AI settings are invalid: {e}", 400) from e
    return cfg, src


def is_configured(cfg: LLMConfig) -> tuple[bool, str]:
    """(ready, reason if not)."""
    if cfg.provider == "anthropic":
        return (bool(cfg.api_key), "" if cfg.api_key else "Add an Anthropic API key.")
    if not cfg.base_url:
        return False, "Set the endpoint URL."
    if cfg.provider == "azure_openai":
        if not (cfg.deployment or cfg.model):
            return False, "Set the Azure deployment name."
        if not cfg.api_key:
            return False, "Add the Azure OpenAI API key."
        return True, ""
    if not cfg.model:
        return False, "Set the model name."
    return True, ""  # local servers often need no key
