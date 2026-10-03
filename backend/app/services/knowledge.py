"""Versioned configuration files (relevance map, product information excerpts, red-flag rules)."""
from __future__ import annotations

from functools import lru_cache

import yaml

from app.llm.framework import norm
from app.settings import CONFIG_DIR


@lru_cache
def relevance() -> dict:
    return yaml.safe_load((CONFIG_DIR / "relevance.yaml").read_text(encoding="utf-8"))


@lru_cache
def drug_info() -> list[dict]:
    return yaml.safe_load((CONFIG_DIR / "drug_info.yaml").read_text(encoding="utf-8"))["medicines"]


@lru_cache
def red_flags() -> dict:
    return yaml.safe_load((CONFIG_DIR / "red_flags.yaml").read_text(encoding="utf-8"))


def drug_facts(name: str, atc: str | None = None) -> dict:
    n = norm(f"{name} {atc or ''}")
    for entry in drug_info():
        if any(m in n for m in entry["match"]):
            return entry
    return {}


def classify_complaint(text: str) -> str:
    n = norm(text)
    best, score = "general", 0
    for cat, cfg in relevance()["categories"].items():
        s = sum(1 for k in cfg.get("keywords", []) if norm(k) in n)
        if s > score:
            best, score = cat, s
    return best
