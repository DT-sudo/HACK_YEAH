"""Explicit response models. Responses are only ever built through these, so internal fields
(working hypotheses, reference maps, raw prompts) cannot leak by accident."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---- auth ----------------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(max_length=40)


class DemoUser(Out):
    id: str
    role: str
    displayName: str
    detail: str | None = None


class LoginOut(Out):
    token: str
    user: DemoUser


# ---- patient: appointments / profile -------------------------------------------------------
class AppointmentOut(Out):
    id: str
    start: str
    doctor: str
    service: str
    clinic: str
    address: str
    phone: str
    preparation: Literal["not_started", "in_progress", "sent", "urgent"]


class PastVisitOut(Out):
    date: str
    reason: str
    doctor: str


class MeOut(Out):
    id: str
    name: str
    initials: str
    birthDate: str
    clinic: str
    demoSuggestion: str | None
    upcoming: AppointmentOut | None
    pastVisits: list[PastVisitOut]


class LifestyleItemOut(Out):
    key: str
    label: str
    labelPl: str
    hint: str
    optional: bool
    value: str
    updatedAt: str | None
    documented: bool


class MedicationItemOut(Out):
    id: str
    name: str
    dose: str
    frequency: str
    start: str | None
    end: str | None
    reason: str | None
    prescriber: str | None
    note: str | None
    current: bool
    updatedAt: str
    documented: bool


class WearableMetricOut(Out):
    label: str
    value: float | int | None
    unit: str


class WearableOut(Out):
    updatedAt: str
    metrics: list[WearableMetricOut]


class ProfileOut(Out):
    lifestyle: list[LifestyleItemOut]
    medications: list[MedicationItemOut]
    wearable: WearableOut | None


class LifestyleIn(BaseModel):
    value: str = Field(max_length=500)


class LifestylePatchIn(BaseModel):
    current: Literal[False]


class MedicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    dose: str = Field("", max_length=60)
    frequency: str = Field("", max_length=80)
    start: str | None = Field(None, max_length=10)
    end: str | None = Field(None, max_length=10)
    reason: str | None = Field(None, max_length=200)
    prescriber: str | None = Field(None, max_length=120)


class MedicationPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: bool | None = None
    end: str | None = Field(None, max_length=10)
    dose: str | None = Field(None, max_length=60)
    frequency: str | None = Field(None, max_length=80)
    reason: str | None = Field(None, max_length=200)


class WearableIn(BaseModel):
    """Aggregates only. Extra fields (location, raw series) are rejected."""
    model_config = ConfigDict(extra="forbid")
    stepsPerDay: int | None = Field(None, ge=0, le=100000)
    restingHr: int | None = Field(None, ge=20, le=250)
    sleepHours: float | None = Field(None, ge=0, le=24)


# ---- patient: intake -----------------------------------------------------------------------
class StartIntakeIn(BaseModel):
    lang: Literal["en", "pl"] = "en"


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    mode: Literal["text", "voice", "choice"] = "text"


class ChatMessageOut(Out):
    from_: Literal["ai", "me"] = Field(alias="from", serialization_alias="from")
    text: str
    mode: str | None = None
    model_config = ConfigDict(populate_by_name=True)


class QuestionOut(Out):
    slot: str
    text: str
    answer_type: Literal["free", "single", "multi", "scale"]
    options: list[str]


class EmergencyOut(Out):
    message: str = "This is not an emergency service. Call 112."
    ruleId: str


class IntakeOut(Out):
    id: str
    state: str
    lang: str
    messages: list[ChatMessageOut]
    question: QuestionOut | None
    progress: float
    emergency: EmergencyOut | None
    degraded: bool


class SummaryOut(Out):
    patientWords: str
    paragraphs: list[str]
    bring: list[str]
    questions: list[str]
    correction: str | None


class ConfirmIn(BaseModel):
    truthful: bool
    correction: str | None = Field(None, max_length=2000)


# ---- doctor --------------------------------------------------------------------------------
class UrgentOut(Out):
    ruleId: str
    trigger: str
    at: str
    contactedBy: str | None
    contactedAt: str | None


class DayPatientOut(Out):
    patientId: str
    name: str
    age: int | None
    sex: str
    time: str
    status: Literal["urgent", "reviewed", "ready", "progress", "none"]
    briefId: str | None
    briefCreatedAt: str | None
    briefFresh: bool = False  # created in the last 15 minutes (server clock)
    urgent: UrgentOut | None
    breakGlass: bool = False


class DayOut(Out):
    date: str
    doctor: str
    patients: list[DayPatientOut]


class CitationOut(Out):
    reference: str
    source: Literal["clinic", "patient"]
    label: str


class FactOut(Out):
    text: str
    date: str | None = None
    citations: list[CitationOut]
    sources: list[str]


class LifestyleFactOut(FactOut):
    updatedAt: str
    monthsAgo: int
    stale: bool


class ReconciledOut(Out):
    by: str
    at: str


class MedicationRowOut(Out):
    reference: str
    name: str
    dose: str
    dates: str
    note: str | None
    status: Literal["current", "past"]
    source: Literal["clinic", "patient"]
    reconciled: ReconciledOut | None


class QAOut(Out):
    label: str
    answer: str


class ReviewOut(Out):
    by: str
    at: str


class GenerationOut(Out):
    provider: str
    prompt_version: str
    dropped_statements: int
    context_records: int
    total_records: int
    degraded: bool
    instruction_like_input: bool = False
    hidden_unresolved: int = 0


class BriefOut(Out):
    id: str
    patientId: str
    createdAt: str | None
    category: str
    chiefComplaint: FactOut
    patientWords: list[str]
    intakeAnswers: list[QAOut]
    patientCorrection: str | None
    medications: list[MedicationRowOut]
    relevantHistory: list[FactOut]
    lifestyle: list[LifestyleFactOut]
    openQuestions: list[str]
    reviewed: ReviewOut | None
    generation: GenerationOut


class SourceOut(Out):
    reference: str
    type: str
    source: Literal["clinic", "patient"]
    title: str
    date: str | None
    fields: list[tuple[str, str]]
    verified: bool
    version: str | None
    raw: dict


class BreakGlassIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class AuditOut(Out):
    who: str
    role: str
    patientId: str | None
    action: str
    resource: str | None
    reason: str | None
    timestamp: str


class LlmCallOut(Out):
    task: str
    provider: str
    promptVersion: str
    latencyMs: int
    inputTokens: int | None
    outputTokens: int | None
    validation: str
    timestamp: str


class SystemOut(Out):
    llmProvider: str
    model: str
    fhirBackend: str
    redFlagRulesVersion: str
    demoToday: str
