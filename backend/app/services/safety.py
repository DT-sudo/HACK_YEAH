"""Emergency safety net. Deterministic, no LLM. Runs on every patient message BEFORE any model call."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.llm.framework import norm
from app.services.knowledge import red_flags


@dataclass
class RedFlag:
    rule_id: str
    label: str
    matched: str


@lru_cache
def _compiled() -> list[tuple[str, str, re.Pattern]]:
    return [(r["id"], r["label"], re.compile("|".join(f"(?:{norm(p)})" for p in r["patterns"])))
            for r in red_flags()["rules"]]


def check_text(text: str) -> RedFlag | None:
    n = norm(text)
    for rid, label, rx in _compiled():
        m = rx.search(n)
        if m:
            return RedFlag(rid, label, m.group(0))
    return None


def check_structured(answer_type: str, value: str, transcript_text: str) -> RedFlag | None:
    for rule in red_flags().get("structured", []):
        if rule["slot_type"] != answer_type:
            continue
        m = re.search(r"\d+", value or "")
        if m and int(m.group()) >= rule["min_value"] and re.search(rule["requires_transcript_pattern"], norm(transcript_text)):
            return RedFlag(rule["id"], rule["label"], f"{m.group()}/10")
    return None


def check_answer_in_context(question: str, answer: str) -> RedFlag | None:
    combined = f"{norm(question)} || {norm(answer)}"
    for rule in red_flags().get("contextual", []):
        if re.search(rule["pattern"], combined):
            return RedFlag(rule["id"], rule["label"], answer)
    return None


def rules_version() -> str:
    return str(red_flags().get("version"))
