"""Validation layer applied to every LLM output before use (ARCHITECTURE.md section 7)."""
from __future__ import annotations

import re

from app.llm.framework import norm

# Diagnostic / recommendation wording. A statement containing any of these is dropped.
_DIAGNOSTIC = [
    r"\bdiagnos", r"\brisk of\b", r"\bat risk\b", r"\byou have\b", r"\bpatient has (a |an )?(likely|probable|possible)",
    r"\brecommend", r"\bprescribe\b", r"\badvis(e|ed) to\b", r"\bshould (start|stop|take|switch|be (started|stopped|treated))",
    r"\bconsider (start|stop|switch|prescrib|treat|refer|order)", r"\blikely\b", r"\bprobabl", r"\bconsistent with\b",
    r"\bindicative of\b", r"\bsuggestive of\b", r"\bsuspect", r"\brule out\b", r"\bdifferential\b", r"\bcaused by\b",
    r"\bdue to\b", r"\btreatment (plan|option)", r"\brisk score\b",
    # Polish
    r"\bdiagnoz", r"\bzaleca", r"\bprawdopodobn", r"\bryzyko\b", r"\bnalezy (wlaczyc|odstawic|przepisac)",
]
_DIAGNOSTIC_RX = re.compile("|".join(_DIAGNOSTIC))

# Disease terms a patient-facing question must not name or hint at (plus the live hypothesis labels).
DISEASE_TERMS = [
    "asthma", "astm", "copd", "pochp", "pneumonia", "zapalenie pluc", "bronchitis", "reflux", "refluks", "gerd",
    "cancer", "nowotw", "rak ", "tumou", "tumor", "tuberculosis", "gruzlic", "covid", "heart failure", "niewydolnosc",
    "ace inhibitor", "inhibitor ace", "side effect", "skutek uboczny", "meniscus", "lakotk", "ligament", "wiezad",
    "tendin", "patellofemoral", "arthritis", "zapalenie stawu", "migraine", "migren", "stroke", "udar", "infarct",
    "zawal", "infection", "infekcj", "embolism", "zator", "diabetes", "cukrzyc", "hypertension", "nadcisnienie",
]

# Heuristic for instruction-like content in patient input. Recorded as a flag only; never blocks text.
_INJECTION_RX = re.compile(
    r"ignore (all|previous|the above)|system prompt|you are now|disregard (the|your)|developer mode|"
    r"<\s*/?\s*(system|instructions?)\s*>|act as|output (the|your) (prompt|instructions)|"
    r"zignoruj (poprzednie|wszystkie)|jestes teraz"
)


def has_diagnostic_wording(text: str) -> bool:
    return bool(_DIAGNOSTIC_RX.search(norm(text)))


def question_hints_disease(text: str, hypothesis_labels: list[str]) -> bool:
    n = norm(text)
    terms = DISEASE_TERMS + [norm(h).replace("_", " ") for h in hypothesis_labels if len(h) > 3]
    return any(t in n for t in terms)


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION_RX.search(norm(text)))
