"""Gemini adapter (demo provider). Same contract as the Claude adapter: synthetic data only,
no tools, structured JSON output only.

Free-tier quota is counted per model, so the adapter walks a chain of models (VC_GEMINI_MODELS):
a model that answers 429 (quota) is benched for as long as Google says, an overloaded one (5xx)
is skipped for this call only. When every model is out, the gateway falls back to the rule engine."""
from __future__ import annotations

import json
import logging
import re
import threading
import time

from google import genai
from google.genai import errors, types

from app.llm.anthropic_provider import wrap_data
from app.settings import get_settings

log = logging.getLogger("vitalcontext.llm")

# Narrow tasks: the intake turn must be fast, the brief benefits from a little more thought.
THINKING = {"t1_intake": "LOW", "t2_summary": "LOW", "t3_brief": "MEDIUM"}
# Gemini often answers 503 "model overloaded" under load; retry with backoff before moving on.
# 429 (quota) is not retried here: the next model in the chain is tried instead.
RETRY = types.HttpRetryOptions(attempts=3, initial_delay=1.0, max_delay=4.0,
                               http_status_codes=[500, 502, 503, 504])
QUOTA_COOLDOWN_S = 60.0  # when a 429 does not say how long to wait
GONE_COOLDOWN_S = 24 * 3600.0  # model retired or unknown (404)


class QuotaExhausted(RuntimeError):
    """No model in the chain could answer this call."""


def retry_after(err: errors.APIError) -> float:
    """Seconds to bench a model after a 429, from the RetryInfo detail (e.g. '15s', '58316s')."""
    for d in ((err.details or {}).get("error") or {}).get("details") or []:
        if d.get("@type", "").endswith("RetryInfo"):
            m = re.match(r"([\d.]+)s", d.get("retryDelay", ""))
            if m:
                return float(m.group(1))
    return QUOTA_COOLDOWN_S


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        s = get_settings()
        self.models = s.gemini_model_chain
        self._benched: dict[str, float] = {}  # model -> monotonic time it may be used again
        self._lock = threading.Lock()
        # Reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the environment unless the key is set in .env.
        self._client = genai.Client(api_key=s.gemini_api_key or None,
                                    http_options=types.HttpOptions(timeout=int(s.llm_timeout_s * 1000),
                                                                    retry_options=RETRY))

    @property
    def model(self) -> str:
        """The model the next call tries first (shown in /system)."""
        return next(iter(self._available()), self.models[0])

    def _available(self) -> list[str]:
        t = time.monotonic()
        with self._lock:
            return [m for m in self.models if self._benched.get(m, 0.0) <= t]

    def _bench(self, model: str, seconds: float, why: str) -> None:
        with self._lock:
            self._benched[model] = time.monotonic() + seconds
        log.warning("gemini model benched model=%s for_s=%d reason=%s", model, seconds, why)

    def run(self, task: str, system: str, payload: dict, schema: dict) -> tuple[dict, dict]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=8000,
            response_mime_type="application/json",
            response_json_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=THINKING[task]),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for model in self._available():
            try:
                response = self._client.models.generate_content(model=model, contents=wrap_data(payload), config=config)
            except errors.ClientError as e:
                if e.code == 429:
                    self._bench(model, retry_after(e), "quota")
                    continue
                if e.code == 404:
                    self._bench(model, GONE_COOLDOWN_S, "not found")
                    continue
                raise
            except errors.ServerError:
                log.warning("gemini model overloaded model=%s task=%s, trying next", model, task)
                continue
            if not response.text:
                raise ValueError("empty or blocked response")
            if model != self.models[0]:
                log.info("gemini served by fallback model=%s task=%s", model, task)
            meta = response.usage_metadata
            usage = {"input_tokens": meta.prompt_token_count if meta else None,
                     "output_tokens": meta.candidates_token_count if meta else None}
            return json.loads(response.text), usage
        raise QuotaExhausted("no Gemini model available")
