"""Runtime configuration. Everything comes from environment variables (or `.env`), never from the repo."""
from __future__ import annotations

import os
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = APP_DIR / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VC_", extra="ignore")

    # Security
    jwt_secret: str = "dev-only-change-me-this-is-not-a-production-secret"  # demo default; production sets VC_JWT_SECRET
    jwt_ttl_minutes: int = 12 * 60

    # Stores
    database_url: str = "sqlite:///./vitalcontext.db"
    fhir_backend: str = "local"  # "local" (in-process, seeded) or "hapi"
    fhir_base_url: str = "http://hapi-fhir:8080/fhir"
    redis_url: str | None = None  # optional; in-process TTL cache otherwise

    # LLM
    llm_provider: str = "gemini"  # auto | mock | anthropic | gemini
    anthropic_model: str = "claude-opus-5"
    gemini_model: str = "gemini-3.5-flash-lite"
    # Fallback chain, comma-separated: on a quota error the next model is used. Overrides gemini_model.
    gemini_models: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash"
    gemini_api_key: str | None = None  # or GEMINI_API_KEY in the environment
    llm_timeout_s: float = 45.0
    intake_question_limit: int = 12

    # Demo
    seed_on_startup: bool = True
    demo_today: str = "2026-10-05"  # the clinic's "today" for the synthetic data set
    demo_mode: bool = True
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def gemini_model_chain(self) -> list[str]:
        chain = [m.strip() for m in self.gemini_models.split(",") if m.strip()]
        return list(dict.fromkeys(chain)) or [self.gemini_model]

    @property
    def resolved_llm_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if self.gemini_api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return "gemini"
        return "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def today() -> date:
    """The clinic's current date. Pinned for the synthetic demo data so 'months ago' stays meaningful."""
    s = get_settings()
    return date.fromisoformat(s.demo_today) if s.demo_today else date.today()


def now() -> datetime:
    """Demo date combined with the real wall-clock time."""
    return datetime.combine(today(), datetime.now().time().replace(microsecond=0))


def iso_now() -> str:
    """FHIR-valid timestamp (a dateTime with a time part must carry a time zone)."""
    offset = datetime.now().astimezone().strftime("%z")
    return now().isoformat() + f"{offset[:3]}:{offset[3:]}"


def midnight(d: date) -> datetime:
    return datetime.combine(d, time())
