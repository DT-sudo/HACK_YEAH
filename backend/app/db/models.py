"""Application state (PostgreSQL in production, SQLite by default). Not medical documentation:
medical documentation lives in the FHIR store."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # login name in the demo
    role: Mapped[str] = mapped_column(String)  # patient | doctor
    display_name: Mapped[str] = mapped_column(String)
    fhir_ref: Mapped[str] = mapped_column(String)  # Patient/... or Practitioner/...
    demo_hint: Mapped[str | None] = mapped_column(String, nullable=True)


class CareAssignment(Base):
    __tablename__ = "care_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    patient_id: Mapped[str] = mapped_column(String)  # FHIR Patient id
    break_glass: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IntakeSession(Base):
    """Draft intake. Becomes a FHIR QuestionnaireResponse when the patient confirms.
    Working hypotheses are deliberately NOT a column: they live only in the session cache."""

    __tablename__ = "intake_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str] = mapped_column(String, index=True)
    appointment_id: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)  # STARTED|COLLECTING|EMERGENCY|COMPLETED|CONFIRMED_BY_PATIENT|SUBMITTED
    lang: Mapped[str] = mapped_column(String, default="en")
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    answers: Mapped[list] = mapped_column(JSON, default=list)  # [{slot,label,value,verbatim?}]
    current_question: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. injection heuristic, degraded mode
    questionnaire_response_id: Mapped[str | None] = mapped_column(String, nullable=True)
    brief_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class UrgentFlag(Base):
    __tablename__ = "urgent_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String)
    appointment_id: Mapped[str] = mapped_column(String)
    rule_id: Mapped[str] = mapped_column(String)
    trigger_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    contacted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BriefReview(Base):
    __tablename__ = "brief_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brief_id: Mapped[str] = mapped_column(String, index=True)
    doctor_id: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    """Append-only. References only, never medical content."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    who: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    patient_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    resource: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)


class LlmCallLog(Base):
    """Gateway metadata only: no prompt or response content is ever stored."""

    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation: Mapped[str] = mapped_column(String)  # ok | retried | fallback | dropped:N
    timestamp: Mapped[datetime] = mapped_column(DateTime)
