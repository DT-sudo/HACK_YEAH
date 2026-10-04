"""Gemini model chain: quota errors move to the next model and bench the exhausted one. Offline (fake client)."""
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.llm import gemini_provider as gp
from app.settings import get_settings


def _quota(delay: str) -> errors.ClientError:
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota", "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})


def _ok(model: str):
    return SimpleNamespace(text=f'{{"model": "{model}"}}', usage_metadata=None)


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_models", "a,b,c")
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test")
    p = gp.GeminiProvider()
    p.calls = []
    p.script = {}  # model -> exception to raise (once per call)

    def generate_content(model, contents, config):
        p.calls.append(model)
        if model in p.script:
            raise p.script[model]
        return _ok(model)

    p._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return p


def run(p):
    return p.run("t1_intake", "sys", {}, {})[0]["model"]


def test_first_model_used_when_healthy(provider):
    assert run(provider) == "a" and provider.calls == ["a"]


def test_quota_moves_to_next_model_and_benches(provider):
    provider.script = {"a": _quota("58316s")}
    assert run(provider) == "b"
    provider.calls.clear()
    assert run(provider) == "b" and provider.calls == ["b"]  # 'a' is not retried while benched
    assert provider.model == "b"


def test_bench_expires(provider, monkeypatch):
    provider.script = {"a": _quota("15s")}
    run(provider)
    provider.script = {}
    now = gp.time.monotonic()
    monkeypatch.setattr(gp.time, "monotonic", lambda: now + 16)
    assert run(provider) == "a"


def test_overloaded_model_skipped_but_not_benched(provider):
    provider.script = {"a": errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "busy"}})}
    assert run(provider) == "b"
    provider.script = {}
    assert run(provider) == "a"


def test_all_exhausted_raises_so_gateway_uses_rules(provider):
    provider.script = {m: _quota("60s") for m in "abc"}
    with pytest.raises(gp.QuotaExhausted):
        run(provider)
    provider.calls.clear()
    with pytest.raises(gp.QuotaExhausted):
        run(provider)
    assert provider.calls == []  # no wasted requests while everything is benched


def test_other_client_errors_are_not_swallowed(provider):
    provider.script = {"a": errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "bad"}})}
    with pytest.raises(errors.ClientError):
        run(provider)


def test_retry_after_defaults_without_retry_info():
    assert gp.retry_after(errors.ClientError(429, {"error": {"code": 429, "message": "q"}})) == gp.QUOTA_COOLDOWN_S


def test_missing_key_runs_on_offline_engine(monkeypatch):
    from app.llm.gateway import LLMGateway
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert LLMGateway(provider="gemini").provider_name == "mock"
