import json

import httpx
import pytest

from tcp_auto.rules import engine
from tcp_auto.rules.llm import LLMConfig, LLMError, OpenAICompatibleGenerator, config_from, is_configured, parse_json_loose

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_DATA_DIR", str(tmp_path))
    for v in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "TCP_LLM_PROVIDER", "TCP_LLM_MODEL",
              "TCP_LLM_BASE_URL", "TCP_LLM_API_KEY", "TCP_LLM_JSON_MODE"):
        monkeypatch.delenv(v, raising=False)
    engine.invalidate_cache()


def reply(content, finish="stop", **msg):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content, **msg}, "finish_reason": finish}]})


def test_openai_compatible_strict_schema():
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url), req.headers.get("authorization"), json.loads(req.content)))
        return reply('{"ok": true}')

    cfg = LLMConfig(provider="openai_compatible", base_url="https://llm.example.com/v1/", model="company-model", api_key="k123")
    out = OpenAICompatibleGenerator(cfg, transport=httpx.MockTransport(handler)).generate_json("sys", "user", SCHEMA)
    assert out == {"ok": True}
    url, auth, body = seen[0]
    assert url == "https://llm.example.com/v1/chat/completions" and auth == "Bearer k123"
    assert body["model"] == "company-model" and body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True and body["messages"][0]["role"] == "system"


def test_falls_back_when_server_lacks_json_schema():
    modes = []

    def handler(req):
        body = json.loads(req.content)
        rf = body.get("response_format", {}).get("type", "prompt")
        modes.append(rf)
        if rf in ("json_schema", "json_object"):
            return httpx.Response(400, json={"error": {"message": f"response_format type {rf} is not supported"}})
        assert "JSON Schema" in body["messages"][0]["content"]  # schema moved into the prompt
        return reply('Sure! ```json\n{"ok": true}\n```')

    cfg = LLMConfig(provider="openai_compatible", base_url="http://localhost:11434/v1", model="llama-local")
    gen = OpenAICompatibleGenerator(cfg, transport=httpx.MockTransport(handler))
    assert gen.generate_json("s", "u", SCHEMA) == {"ok": True}
    assert modes == ["json_schema", "json_object", "prompt"]
    gen.generate_json("s", "u", SCHEMA)  # remembers what this server supports
    assert modes[3:] == ["prompt"]


def test_azure_url_and_key_header():
    seen = {}

    def handler(req):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("api-key"), json.loads(req.content)
        return reply('{"ok": true}')

    cfg = LLMConfig(provider="azure_openai", base_url="https://acme.openai.azure.com", deployment="tcp-gpt", api_key="az", api_version="2024-10-21")
    OpenAICompatibleGenerator(cfg, transport=httpx.MockTransport(handler)).generate_json("s", "u", SCHEMA)
    assert seen["url"] == "https://acme.openai.azure.com/openai/deployments/tcp-gpt/chat/completions?api-version=2024-10-21"
    assert seen["key"] == "az" and "model" not in seen["body"]


@pytest.mark.parametrize("resp,status,needle", [
    (httpx.Response(401, json={"error": {"message": "bad key"}}), 400, "credentials"),
    (httpx.Response(404, json={"error": {"message": "no such model"}}), 400, "not found"),
    (httpx.Response(429, json={}), 429, "rate-limiting"),
    (httpx.Response(503, json={}), 502, "service error"),
])
def test_http_errors_are_friendly(resp, status, needle):
    cfg = LLMConfig(provider="openai_compatible", base_url="https://x/v1", model="m", json_mode="json_schema")
    with pytest.raises(LLMError) as e:
        OpenAICompatibleGenerator(cfg, transport=httpx.MockTransport(lambda r: resp)).generate_json("s", "u", SCHEMA)
    assert e.value.status == status and needle in str(e.value)


def test_content_filter_and_truncation():
    cfg = LLMConfig(provider="openai_compatible", base_url="https://x/v1", model="m")
    with pytest.raises(LLMError) as e:
        OpenAICompatibleGenerator(cfg, transport=httpx.MockTransport(lambda r: reply(None, finish="content_filter"))).generate_json("s", "u", SCHEMA)
    assert e.value.status == 422
    with pytest.raises(LLMError) as e:
        OpenAICompatibleGenerator(cfg, transport=httpx.MockTransport(lambda r: reply('{"ok"', finish="length"))).generate_json("s", "u", SCHEMA)
    assert e.value.status == 413


def test_connection_error_is_friendly():
    def boom(req):
        raise httpx.ConnectError("refused")

    cfg = LLMConfig(provider="openai_compatible", base_url="http://10.0.0.5:8000/v1", model="m")
    with pytest.raises(LLMError) as e:
        OpenAICompatibleGenerator(cfg, transport=httpx.MockTransport(boom)).generate_json("s", "u", SCHEMA)
    assert e.value.status == 503 and "10.0.0.5" in str(e.value)


def test_parse_json_loose():
    assert parse_json_loose('{"a": 1}') == {"a": 1}
    assert parse_json_loose('Here you go:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert parse_json_loose('Result: {"a": 3} hope that helps') == {"a": 3}
    with pytest.raises(LLMError):
        parse_json_loose("no json here")


def test_env_overrides_settings(monkeypatch):
    monkeypatch.setenv("TCP_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("TCP_LLM_BASE_URL", "https://gateway.corp/v1")
    monkeypatch.setenv("TCP_LLM_MODEL", "corp-llm")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cfg, src = config_from({"llm": {"provider": "anthropic", "api_key": "ignored-for-provider"}})
    assert cfg.provider == "openai_compatible" and cfg.base_url == "https://gateway.corp/v1" and cfg.model == "corp-llm"
    assert cfg.api_key == "ignored-for-provider"  # saved key kept; env key only fills a missing one
    assert src["base_url"] == "environment"
    assert is_configured(cfg) == (True, "")


def test_local_server_needs_no_key():
    assert is_configured(LLMConfig(provider="openai_compatible", base_url="http://localhost:11434/v1", model="m"))[0]
    assert not is_configured(LLMConfig(provider="openai_compatible", base_url="http://localhost:11434/v1"))[0]
    assert not is_configured(LLMConfig(provider="anthropic"))[0]


def test_settings_switch_provider_and_hide_key():
    from tcp_auto.rules.assistant import save_settings, settings_status

    save_settings(api_key="sk-ant-xyz9", provider="anthropic")
    st = save_settings(provider="openai_compatible", base_url="http://localhost:11434/v1", model="local-model")
    assert st["provider"] == "openai_compatible" and st["key_hint"] is None  # Anthropic key not reused for another service
    assert st["configured"] and "api_key" not in st and "sk-ant" not in json.dumps(st)
    assert any(p["id"] == "ollama" for p in settings_status()["presets"])


def test_legacy_settings_migrate(tmp_path):
    from tcp_auto.rules.assistant import _settings_path, settings_status

    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps({"anthropic_api_key": "sk-ant-old1", "model": "claude-opus-5-5"}))
    st = settings_status()
    assert st["provider"] == "anthropic" and st["key_hint"] == "…old1" and st["configured"]


def test_draft_with_openai_compatible_provider():
    from tcp_auto.rules.assistant import draft, save_settings

    save_settings(provider="openai_compatible", base_url="https://llm.corp/v1", model="corp-llm")
    payload = {"summary": "Peak hours.", "questions": [], "changes": [
        {"op": "set", "key": "peak_hours", "value_json": json.dumps({"road_class": ["arterial"], "weekdays": ["6:30 am-8:30 am"]}),
         "section": "3.1", "quote": "No lane closures 6:30-8:30 a.m.", "note": "", "confidence": "high"}]}
    gen = OpenAICompatibleGenerator(LLMConfig(provider="openai_compatible", base_url="https://llm.corp/v1", model="corp-llm"),
                                    transport=httpx.MockTransport(lambda r: reply(json.dumps(payload))))
    p = draft("cities/AZ/mesa", None, "Mesa TTCM", "", "No lane closures 6:30-8:30 a.m.", generator=gen)
    assert p.model == "openai_compatible:corp-llm" and p.changes[0].value["weekdays"] == ["06:30-08:30"] and not p.changes[0].errors


def test_connection_test_uses_generator():
    from tcp_auto.rules.assistant import save_settings, test_connection

    save_settings(provider="openai_compatible", base_url="https://llm.corp/v1", model="corp-llm")
    gen = OpenAICompatibleGenerator(LLMConfig(provider="openai_compatible", base_url="https://llm.corp/v1", model="corp-llm"),
                                    transport=httpx.MockTransport(lambda r: reply('{"ok": true, "speed_limit_mph": 35}')))
    out = test_connection(generator=gen)
    assert out["ok"] and out["sample"]["speed_limit_mph"] == 35
