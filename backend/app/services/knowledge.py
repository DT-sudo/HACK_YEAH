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
def registry() -> dict:
    """Public product information (simulated snapshot of the Polish URPL registry)."""
    return yaml.safe_load((CONFIG_DIR / "registry_snapshot.yaml").read_text(encoding="utf-8"))


@lru_cache
def red_flags() -> dict:
    return yaml.safe_load((CONFIG_DIR / "red_flags.yaml").read_text(encoding="utf-8"))


def drug_facts(name: str, atc: str | None = None) -> dict:
    """Registry facts for a medicine: class, undesirable effects (very common + common), registry reference."""
    n = norm(f"{name} {atc or ''}")
    for entry in registry()["products"]:
        if any(m in n for m in entry["match"]):
            effects = entry.get("effects", [])
            return {**entry,
                    "listed_side_effects": [e["term"] for e in effects if e["freq"] in ("very common", "common")],
                    "registry_ref": f"DocumentReference/{entry['id']}"}
    return {}


REGISTRY_TAG = {"system": "https://vitalcontext.example/tags", "code": "public-registry"}


def registry_documents() -> list[dict]:
    """Each registry product as a FHIR DocumentReference, so registry facts are citable like any record."""
    src = registry()["source"]
    docs = []
    for p in registry()["products"]:
        groups: dict[str, list[str]] = {}
        for e in p.get("effects", []):
            groups.setdefault(e["freq"], []).append(e["term"])
        text = "; ".join(f"{freq}: {', '.join(terms)}" for freq, terms in groups.items()) or "none listed"
        docs.append({
            "resourceType": "DocumentReference", "id": p["id"], "status": "current",
            "meta": {"tag": [REGISTRY_TAG]},
            "type": {"text": f"Product information (SmPC 4.8): {p['substance']}"},
            "date": f"{src['snapshot']}T00:00:00+02:00",  # DocumentReference.date is an instant
            "description": f"Undesirable effects. {text[:1].upper()}{text[1:]}.",
            "author": [{"display": f"{src['name']}{' (simulated snapshot)' if src.get('simulated') else ''}"}],
            "context": {"related": [{"display": f"ATC {p['atc']} · {p['registry_id']}"}]},
            "content": [{"attachment": {"contentType": "text/html", "url": src["url"],
                                        "title": f"{p['substance']} · {p['registry_id']}"}}],
        })
    return docs


def classify_complaint(text: str) -> str:
    n = norm(text)
    best, score = "general", 0
    for cat, cfg in relevance()["categories"].items():
        s = sum(1 for k in cfg.get("keywords", []) if norm(k) in n)
        if s > score:
            best, score = cat, s
    return best
