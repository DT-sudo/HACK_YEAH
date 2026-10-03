"""Intake service: the chat as a state machine.

STARTED -> COLLECTING -> (EMERGENCY | COMPLETED) -> CONFIRMED_BY_PATIENT -> SUBMITTED

Every patient message: safety check (deterministic, before any LLM) -> transcript -> T1 -> validate
-> update state. Working hypotheses live only in the session cache and are discarded at the end.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IntakeSession, UrgentFlag, User
from app.fhir.client import FhirStore
from app.llm import framework
from app.llm.gateway import get_gateway
from app.llm.mock_provider import MockProvider
from app.llm.validation import has_diagnostic_wording, looks_like_injection, question_hints_disease
from app.services import audit, brief as brief_service, profile, safety, session_cache
from app.services.context import build_context_pack
from app.services.knowledge import classify_complaint
from app.settings import get_settings, iso_now, now

ACTIVE = ("STARTED", "COLLECTING", "COMPLETED")
EXPECTED_QUESTIONS = 8

CLOSING = {
    "en": "Thank you, that's everything I need. Next you'll see a summary to check before it goes to {doctor}.",
    "pl": "Dziękuję, to wszystko, czego potrzebuję. Za chwilę zobaczy Pan/Pani podsumowanie do sprawdzenia, zanim trafi do: {doctor}.",
}


class IntakeError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Appointment:
    id: str
    start: str
    practitioner_ref: str
    practitioner_name: str
    service: str
    visit_type: str | None = None  # e.g. "adhd-followup": sets the intake category up front


def upcoming_appointment(fhir: FhirStore, patient_id: str) -> Appointment | None:
    appts = [a for a in fhir.search("Appointment", patient=f"Patient/{patient_id}") if a.get("status") == "booked"]
    if not appts:
        return None
    a = sorted(appts, key=lambda x: x.get("start", ""))[0]
    prac = next((p["actor"] for p in a.get("participant", []) if p["actor"]["reference"].startswith("Practitioner/")), {})
    st = (a.get("serviceType") or [{}])[0]
    return Appointment(a["id"], a["start"], prac.get("reference", ""), prac.get("display", "your doctor"),
                       st.get("text", "Visit"), next((c.get("code") for c in st.get("coding", [])), None))


FOLLOWUP_CATEGORY = {"adhd-followup": "adhd_followup"}


def latest_session(db: Session, patient_id: str, appointment_id: str) -> IntakeSession | None:
    return db.scalars(select(IntakeSession).where(IntakeSession.patient_id == patient_id,
                                                   IntakeSession.appointment_id == appointment_id)
                      .order_by(IntakeSession.created_at.desc())).first()


def start_or_resume(db: Session, fhir: FhirStore, user: User, patient_id: str, lang: str) -> IntakeSession:
    appt = upcoming_appointment(fhir, patient_id)
    if not appt:
        raise IntakeError(404, "No upcoming appointment")
    s = latest_session(db, patient_id, appt.id)
    if s and s.state in ACTIVE:
        if s.lang != lang and s.state != "COMPLETED":
            s.lang = lang
            db.commit()
        return s
    if s and s.state in ("EMERGENCY", "SUBMITTED", "CONFIRMED_BY_PATIENT"):
        return s
    first = user.display_name.split()[0]
    category = FOLLOWUP_CATEGORY.get(appt.visit_type or "")
    q = (framework.followup_opening(lang, first, appt.practitioner_name) if category
         else framework.complaint_slot(lang, first, appt.practitioner_name))
    s = IntakeSession(id=f"in-{uuid.uuid4().hex[:10]}", patient_id=patient_id, appointment_id=appt.id, state="STARTED",
                      lang=lang, category=category, transcript=[{"from": "ai", "text": q["text"], "at": iso_now()}], answers=[],
                      current_question=q, question_count=0, flags={}, created_at=now(), updated_at=now())
    db.add(s)
    db.commit()
    audit.record(db, user.id, "patient", "intake.start", patient_id, f"IntakeSession/{s.id}")
    return s


def _emergency(db: Session, s: IntakeSession, flag: safety.RedFlag, user: User, said: str) -> IntakeSession:
    s.state = "EMERGENCY"
    s.current_question = None
    s.flags = {**s.flags, "red_flag": {"rule_id": flag.rule_id, "label": flag.label, "rules_version": safety.rules_version()}}
    session_cache.discard(s.id)
    db.add(UrgentFlag(patient_id=s.patient_id, session_id=s.id, appointment_id=s.appointment_id, rule_id=flag.rule_id,
                      trigger_text=f'{flag.label}. Patient {said}: "{_clip(s.transcript[-1]["text"])}"', created_at=now()))
    s.updated_at = now()
    db.commit()
    audit.record(db, user.id, "patient", "intake.emergency", s.patient_id, f"IntakeSession/{s.id}", reason=flag.rule_id)
    return s


def _clip(t: str, n: int = 160) -> str:
    return t if len(t) <= n else t[: n - 1] + "…"


def post_message(db: Session, fhir: FhirStore, user: User, s: IntakeSession, text: str, mode: str) -> IntakeSession:
    if s.state not in ("STARTED", "COLLECTING"):
        raise IntakeError(409, f"Intake is {s.state.lower()}")
    text = text.strip()
    if not text:
        raise IntakeError(422, "Empty message")
    q = s.current_question or {}
    s.transcript = s.transcript + [{"from": "me", "text": text, "mode": mode, "at": iso_now()}]

    # 1. Safety net first. Deterministic; runs on typed, spoken and tapped answers alike.
    said = {"voice": "said", "choice": "chose"}.get(mode, "typed")
    flag = safety.check_text(text) or safety.check_answer_in_context(q.get("text", ""), text)
    if not flag and q.get("answer_type") == "scale":
        flag = safety.check_structured("scale", text, " ".join(m["text"] for m in s.transcript if m["from"] == "me"))
    if flag:
        return _emergency(db, s, flag, user, said)

    # 2. Heuristic injection flag: metadata only, text is never blocked or rewritten.
    if looks_like_injection(text):
        s.flags = {**s.flags, "instruction_like_input": True}

    s.state = "COLLECTING"
    if q.get("slot") == "complaint" and not s.category:
        s.category = classify_complaint(text)
    category = s.category or "general"
    ctx = build_context_pack(fhir, s.patient_id, category)
    hyps = session_cache.get_hypotheses(s.id)
    payload = {"context_pack": ctx.pack, "category": category, "answers": s.answers, "working_hypotheses": hyps,
               "current_question": q, "latest_message": {"text": text, "mode": mode}, "lang": s.lang,
               "question_count": s.question_count, "question_limit": get_settings().intake_question_limit}
    res = get_gateway().run("t1_intake", payload, db)
    out = res.output
    if res.degraded:
        s.flags = {**s.flags, "degraded": True}

    # 3. Merge answers. Patient words for the opening complaint are stored verbatim by code.
    answers = {a["slot"]: a for a in s.answers}
    for ea in out.extracted_answers:
        answers[ea.slot] = {"slot": ea.slot, "label": ea.label, "value": ea.value}
    if q.get("slot") == "complaint":
        answers["complaint"] = {"slot": "complaint", "label": "Reason for visit", "value": text, "verbatim": True}
    elif q.get("answer_type") == "free" and q.get("slot"):  # free text is the patient's own words: verbatim
        answers[q["slot"]] = {"slot": q["slot"], "label": q.get("label") or q["slot"].replace("_", " ").capitalize(),
                              "value": text, "verbatim": True}
    elif q.get("slot") and q["slot"] not in answers:
        answers[q["slot"]] = {"slot": q["slot"], "label": q.get("label") or q["slot"].replace("_", " ").capitalize(), "value": text}
    s.answers = list(answers.values())
    session_cache.set_hypotheses(s.id, [h.model_dump() for h in out.working_hypotheses])

    # 4. Validate the next question.
    nq = out.next_question.model_dump() if out.next_question else None
    labels = [h.label for h in out.working_hypotheses]
    if nq and (question_hints_disease(nq["text"], labels) or has_diagnostic_wording(nq["text"]) or nq["slot"] in answers):
        nq = _framework_next(s, ctx.pack)  # replace with the next framework question
    if nq and nq["answer_type"] in ("single", "multi") and not nq["options"]:
        nq["answer_type"] = "free"
    stop = out.stop or nq is None or s.question_count >= get_settings().intake_question_limit
    if stop:
        s.state = "COMPLETED"
        s.current_question = None
        appt = upcoming_appointment(fhir, s.patient_id)
        closing = CLOSING.get(s.lang, CLOSING["en"]).format(doctor=appt.practitioner_name if appt else "your doctor")
        s.transcript = s.transcript + [{"from": "ai", "text": closing, "at": iso_now()}]
    else:
        slot = framework.slot_by_id(category, nq["slot"])
        nq["label"] = slot.label if slot else nq["slot"].replace("_", " ").capitalize()
        s.current_question = nq
        s.question_count += 1
        s.transcript = s.transcript + [{"from": "ai", "text": nq["text"], "at": iso_now()}]
    s.updated_at = now()
    db.commit()
    return s


def _framework_next(s: IntakeSession, pack: dict) -> dict | None:
    out = MockProvider().t1({"category": s.category, "lang": s.lang, "answers": s.answers, "context_pack": pack,
                             "current_question": {}, "question_count": s.question_count,
                             "question_limit": get_settings().intake_question_limit})
    return out["next_question"]


def progress(s: IntakeSession) -> float:
    if s.state in ("COMPLETED", "CONFIRMED_BY_PATIENT", "SUBMITTED", "EMERGENCY"):
        return 1.0 if s.state != "COMPLETED" else 0.9
    answered = len([a for a in s.answers if a["slot"] != "complaint"])
    return round(min(0.85, 0.05 + 0.8 * answered / EXPECTED_QUESTIONS), 2)


def summary(db: Session, fhir: FhirStore, s: IntakeSession) -> dict:
    if s.state not in ("COMPLETED", "CONFIRMED_BY_PATIENT", "SUBMITTED"):
        raise IntakeError(409, "Summary is available once the chat is complete")
    if not s.summary:
        reported = [m["name"] for m in profile.get_profile(fhir, s.patient_id)["medications"] if m["current"]]
        res = get_gateway().run("t2_summary", {"category": s.category, "answers": s.answers, "lang": s.lang,
                                               "reported_medicines": reported}, db)
        o = res.output
        clean = [p for p in o.summary_text if not has_diagnostic_wording(p)]
        s.summary = {"paragraphs": clean, "bring": [b for b in o.bring_items if not has_diagnostic_wording(b)],
                     "questions": [x for x in o.suggested_questions if not has_diagnostic_wording(x)],
                     "dropped": len(o.summary_text) - len(clean)}
        db.commit()
    complaint = next((a["value"] for a in s.answers if a["slot"] == "complaint"), "")
    return {"patientWords": complaint, **s.summary, "correction": s.correction}


def confirm(db: Session, fhir: FhirStore, user: User, s: IntakeSession, truthful: bool, correction: str | None) -> IntakeSession:
    if s.state != "COMPLETED":
        raise IntakeError(409, "Only a completed intake can be confirmed")
    if not truthful:
        raise IntakeError(422, "Please confirm your answers are true to the best of your knowledge")
    if correction is not None:
        s.correction = correction.strip() or None
    s.state = "CONFIRMED_BY_PATIENT"
    db.commit()

    # Confirmed intake becomes medical documentation (QuestionnaireResponse).
    items = [{"linkId": a["slot"], "text": a["label"], "answer": [{"valueString": a["value"]}]} for a in s.answers]
    if s.correction:
        items.append({"linkId": "patient-correction", "text": "Patient correction", "answer": [{"valueString": s.correction}]})
    items.append({"linkId": "transcript", "text": "Chat transcript",
                  "item": [{"linkId": f"t{i}", "text": m["from"], "answer": [{"valueString": m["text"]}]}
                           for i, m in enumerate(s.transcript)]})
    modes = {m.get("mode") for m in s.transcript if m["from"] == "me"}
    qr = fhir.create({
        "resourceType": "QuestionnaireResponse", "status": "completed", "questionnaire": "Questionnaire/vc-intake-v1",
        "subject": {"reference": f"Patient/{s.patient_id}"}, "source": {"reference": f"Patient/{s.patient_id}"},
        "authored": iso_now(), "item": items,
        "extension": [{"url": "https://vitalcontext.example/fhir/StructureDefinition/intake-mode",
                       "valueString": "AI-guided chat, " + ("voice" if "voice" in modes else "text")}],
    })
    s.questionnaire_response_id = qr["id"]
    composition, used_profile_refs = brief_service.generate(db, fhir, s, f"QuestionnaireResponse/{qr['id']}")
    s.brief_id = composition["id"]
    profile.mark_documented(fhir, used_profile_refs)
    s.state = "SUBMITTED"
    s.updated_at = now()
    session_cache.discard(s.id)  # working hypotheses are never persisted
    db.commit()
    audit.record(db, user.id, "patient", "intake.confirm", s.patient_id, f"QuestionnaireResponse/{qr['id']}")
    return s
