"""LLM Gateway: the only module that talks to a model provider.

* per-task versioned prompt + JSON schema
* output validated against the schema; malformed -> one retry -> deterministic fallback
* metadata-only logging (task, provider, prompt version, latency, tokens, validation result)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.db.models import LlmCallLog
from app.llm.mock_provider import MockProvider
from app.llm.schemas import TASKS
from app.settings import get_settings, now

log = logging.getLogger("vitalcontext.llm")
PROMPT_DIR = Path(__file__).parent / "prompts"


def load_prompt(task: str) -> tuple[str, str]:
    text = (PROMPT_DIR / f"{task}.md").read_text(encoding="utf-8")
    first = text.splitlines()[0]
    version = first.split(":", 1)[1].strip() if first.lower().startswith("version:") else "unversioned"
    return version, text


@dataclass
class GatewayResult:
    output: BaseModel
    provider: str
    prompt_version: str
    degraded: bool  # True when the deterministic fallback produced the output


class LLMGateway:
    def __init__(self, provider: str | None = None) -> None:
        self.fallback = MockProvider()
        name = provider or get_settings().resolved_llm_provider
        try:
            if name == "anthropic":
                from app.llm.anthropic_provider import AnthropicProvider
                self.provider = AnthropicProvider()
            elif name == "gemini":
                from app.llm.gemini_provider import GeminiProvider
                self.provider = GeminiProvider()
            else:
                self.provider = self.fallback
        except Exception as e:  # e.g. no API key: run on the offline engine instead of failing every request
            log.warning("llm provider %s unavailable (%s), using the offline engine", name, e)
            self.provider = self.fallback

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def run(self, task: str, payload: dict, db: Session | None = None) -> GatewayResult:
        model_cls, schema = TASKS[task]
        version, system = load_prompt(task)
        attempts = [self.provider, self.provider] if self.provider is not self.fallback else [self.provider]
        for i, provider in enumerate(attempts):
            t0 = time.perf_counter()
            try:
                raw, usage = provider.run(task, system, payload, schema)
                out = model_cls.model_validate(raw)
            except (ValidationError, ValueError, KeyError, StopIteration) as e:
                self._log(db, task, provider.name, version, t0, {}, f"invalid:{type(e).__name__}")
                continue
            except Exception as e:  # provider/network errors: never let them break intake
                log.warning("llm provider error task=%s provider=%s err=%s", task, provider.name, type(e).__name__)
                self._log(db, task, provider.name, version, t0, {}, f"error:{type(e).__name__}")
                break
            self._log(db, task, provider.name, version, t0, usage, "ok" if i == 0 else "retried")
            return GatewayResult(out, provider.name, version, degraded=provider is self.fallback and self.provider is not self.fallback)
        # Safe fallback: deterministic rules / static framework questionnaire.
        t0 = time.perf_counter()
        raw, usage = self.fallback.run(task, system, payload, schema)
        self._log(db, task, self.fallback.name, version, t0, usage, "fallback")
        return GatewayResult(model_cls.model_validate(raw), self.fallback.name, version, degraded=True)

    @staticmethod
    def _log(db, task, provider, version, t0, usage, result) -> None:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("llm task=%s provider=%s prompt=%s latency_ms=%d result=%s", task, provider, version, ms, result)
        if db is not None:
            db.add(LlmCallLog(task=task, provider=provider, prompt_version=version, latency_ms=ms,
                              input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                              validation=result, timestamp=now()))


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
