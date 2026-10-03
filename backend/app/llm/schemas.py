"""Fixed output contracts for the three LLM tasks. The JSON schemas are sent to the provider's
structured-output mode; the Pydantic models re-validate every response (LLM output is untrusted)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- T1 Intake turn -------------------------------------------------------------------------
class ExtractedAnswer(_Strict):
    slot: str = Field(max_length=40)
    label: str = Field(max_length=60)
    value: str = Field(max_length=600)


class WorkingHypothesis(_Strict):
    label: str = Field(max_length=80)
    status: Literal["open", "unlikely"]


class NextQuestion(_Strict):
    slot: str = Field(max_length=40)
    text: str = Field(max_length=400)
    answer_type: Literal["free", "single", "multi", "scale"]
    options: list[str] = Field(default_factory=list, max_length=8)


class T1Output(_Strict):
    extracted_answers: list[ExtractedAnswer]
    working_hypotheses: list[WorkingHypothesis]
    next_question: NextQuestion | None
    stop: bool


# ---- T2 Patient summary ---------------------------------------------------------------------
class T2Output(_Strict):
    summary_text: list[str] = Field(max_length=12)  # short plain-language paragraphs
    bring_items: list[str] = Field(max_length=8)
    suggested_questions: list[str] = Field(max_length=6)


# ---- T3 Brief -------------------------------------------------------------------------------
class Connection(_Strict):
    statement: str = Field(max_length=500)
    refs: list[str] = Field(max_length=6)


class T3Output(_Strict):
    chief_complaint: str = Field(max_length=300)
    connections: list[Connection] = Field(max_length=12)
    open_questions: list[str] = Field(max_length=8)


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


_S = {"type": "string"}
_SA = {"type": "array", "items": _S}

T1_SCHEMA = _obj({
    "extracted_answers": {"type": "array", "items": _obj({"slot": _S, "label": _S, "value": _S})},
    "working_hypotheses": {"type": "array", "items": _obj({"label": _S, "status": {"type": "string", "enum": ["open", "unlikely"]}})},
    "next_question": {"anyOf": [
        _obj({"slot": _S, "text": _S, "answer_type": {"type": "string", "enum": ["free", "single", "multi", "scale"]}, "options": _SA}),
        {"type": "null"}]},
    "stop": {"type": "boolean"},
})
T2_SCHEMA = _obj({"summary_text": _SA, "bring_items": _SA, "suggested_questions": _SA})
T3_SCHEMA = _obj({
    "chief_complaint": _S,
    "connections": {"type": "array", "items": _obj({"statement": _S, "refs": _SA})},
    "open_questions": _SA,
})

TASKS = {
    "t1_intake": (T1Output, T1_SCHEMA),
    "t2_summary": (T2Output, T2_SCHEMA),
    "t3_brief": (T3Output, T3_SCHEMA),
}
