"""Patient endpoints. patient_id always comes from the token."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import models as M
from app.api.deps import fhir_dep, patient_id_of, patient_user
from app.db.models import IntakeSession, UrgentFlag, User
from app.db.session import get_db
from app.fhir.client import FhirStore
from app.fhir.seed import CLINIC
from app.services import audit, brief as brief_service, checkins, intake, profile, session_cache, trends
from app.services.checkins import CheckinError
from app.settings import today
from app.services.intake import IntakeError
from app.services.profile import ProfileError

router = APIRouter(prefix="/me", tags=["patient"])


def _profile_error(e: ProfileError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message})


def _intake_error(e: IntakeError) -> HTTPException:
    return HTTPException(e.status, e.message)


def _own_session(db: Session, user: User, sid: str) -> IntakeSession:
    s = db.get(IntakeSession, sid)
    if not s or s.patient_id != patient_id_of(user):  # never reveal other patients' sessions
        raise HTTPException(404, "Intake not found")
    return s


def intake_out(s: IntakeSession) -> M.IntakeOut:
    q = s.current_question
    flag = (s.flags or {}).get("red_flag")
    return M.IntakeOut(
        id=s.id, state=s.state, lang=s.lang,
        messages=[M.ChatMessageOut(**{"from": m["from"], "text": m["text"], "mode": m.get("mode")}) for m in s.transcript],
        question=M.QuestionOut(slot=q["slot"], text=q["text"], answer_type=q["answer_type"], options=q.get("options", [])) if q else None,
        progress=intake.progress(s),
        emergency=M.EmergencyOut(ruleId=flag["rule_id"]) if s.state == "EMERGENCY" and flag else None,
        degraded=bool((s.flags or {}).get("degraded")),
    )


@router.get("", response_model=M.MeOut)
def me(user: User = Depends(patient_user), db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    pid = patient_id_of(user)
    p = fhir.read("Patient", pid) or {}
    appt = intake.upcoming_appointment(fhir, pid)
    upcoming = None
    if appt:
        s = intake.latest_session(db, pid, appt.id)
        urgent = db.scalars(select(UrgentFlag).where(UrgentFlag.patient_id == pid, UrgentFlag.appointment_id == appt.id)).first()
        prep = ("urgent" if urgent else "sent" if s and s.state == "SUBMITTED" else
                "in_progress" if s and (s.question_count > 0 or s.state in ("COLLECTING", "COMPLETED")) else "not_started")
        upcoming = M.AppointmentOut(id=appt.id, start=appt.start, doctor=appt.practitioner_name, service=appt.service,
                                    clinic=CLINIC, address="ul. Józefa 14, 31-056 Kraków", phone="+48 12 000 00 00",
                                    preparation=prep)
    past = sorted(fhir.search("Encounter", patient=f"Patient/{pid}"), key=lambda e: e["period"]["start"], reverse=True)
    audit.record(db, user.id, "patient", "profile.read", pid)
    return M.MeOut(
        id=pid, name=user.display_name, initials="".join(w[0] for w in user.display_name.split()[:2]),
        birthDate=p.get("birthDate", ""), clinic=CLINIC, demoSuggestion=user.demo_hint, upcoming=upcoming,
        pastVisits=[M.PastVisitOut(date=e["period"]["start"], reason=(e.get("reasonCode") or [{}])[0].get("text", "Visit"),
                                   doctor=(e.get("participant") or [{}])[0].get("individual", {}).get("display", "")) for e in past[:6]],
    )


# ---- profile ---------------------------------------------------------------------------------
@router.get("/profile", response_model=M.ProfileOut)
def get_profile(user: User = Depends(patient_user), fhir: FhirStore = Depends(fhir_dep)):
    return profile.get_profile(fhir, patient_id_of(user))


@router.get("/profile/lifestyle", response_model=list[M.LifestyleItemOut])
def get_lifestyle(user: User = Depends(patient_user), fhir: FhirStore = Depends(fhir_dep)):
    return profile.get_profile(fhir, patient_id_of(user))["lifestyle"]


@router.put("/profile/lifestyle/{key}", response_model=M.ProfileOut)
def put_lifestyle(key: str, body: M.LifestyleIn, user: User = Depends(patient_user), db: Session = Depends(get_db),
                  fhir: FhirStore = Depends(fhir_dep)):
    try:
        profile.put_lifestyle(fhir, patient_id_of(user), key, body.value)
    except ProfileError as e:
        raise _profile_error(e)
    audit.record(db, user.id, "patient", "profile.lifestyle.update", patient_id_of(user), f"lifestyle:{key}")
    return profile.get_profile(fhir, patient_id_of(user))


@router.delete("/profile/lifestyle/{key}", response_model=M.ProfileOut)
def delete_lifestyle(key: str, user: User = Depends(patient_user), db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    try:
        profile.delete_lifestyle(fhir, patient_id_of(user), key)
    except ProfileError as e:
        raise _profile_error(e)
    audit.record(db, user.id, "patient", "profile.lifestyle.delete", patient_id_of(user), f"lifestyle:{key}")
    return profile.get_profile(fhir, patient_id_of(user))


@router.patch("/profile/lifestyle/{key}", response_model=M.ProfileOut)
def mark_lifestyle_not_current(key: str, body: M.LifestylePatchIn, user: User = Depends(patient_user),
                               db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    profile.delete_lifestyle(fhir, patient_id_of(user), key, mark_not_current=True)
    audit.record(db, user.id, "patient", "profile.lifestyle.not_current", patient_id_of(user), f"lifestyle:{key}")
    return profile.get_profile(fhir, patient_id_of(user))


@router.get("/profile/medications", response_model=list[M.MedicationItemOut])
def list_meds(user: User = Depends(patient_user), fhir: FhirStore = Depends(fhir_dep)):
    return profile.get_profile(fhir, patient_id_of(user))["medications"]


@router.post("/profile/medications", response_model=M.ProfileOut, status_code=201)
def add_med(body: M.MedicationIn, user: User = Depends(patient_user), db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    r = profile.add_medication(fhir, patient_id_of(user), body.model_dump())
    audit.record(db, user.id, "patient", "profile.medication.add", patient_id_of(user), f"MedicationStatement/{r['id']}")
    return profile.get_profile(fhir, patient_id_of(user))


@router.patch("/profile/medications/{mid}", response_model=M.ProfileOut)
def patch_med(mid: str, body: M.MedicationPatchIn, user: User = Depends(patient_user), db: Session = Depends(get_db),
              fhir: FhirStore = Depends(fhir_dep)):
    try:
        profile.patch_medication(fhir, patient_id_of(user), mid, body.model_dump(exclude_none=True))
    except ProfileError as e:
        raise _profile_error(e)
    audit.record(db, user.id, "patient", "profile.medication.update", patient_id_of(user), f"MedicationStatement/{mid}")
    return profile.get_profile(fhir, patient_id_of(user))


@router.delete("/profile/medications/{mid}", response_model=M.ProfileOut)
def delete_med(mid: str, user: User = Depends(patient_user), db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    try:
        profile.delete_medication(fhir, patient_id_of(user), mid)
    except ProfileError as e:
        raise _profile_error(e)
    audit.record(db, user.id, "patient", "profile.medication.delete", patient_id_of(user), f"MedicationStatement/{mid}")
    return profile.get_profile(fhir, patient_id_of(user))


@router.put("/profile/wearable", response_model=M.ProfileOut)
def put_wearable(body: M.WearableIn, user: User = Depends(patient_user), db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    profile.put_wearable(fhir, patient_id_of(user), body.stepsPerDay, body.restingHr, body.sleepHours)
    audit.record(db, user.id, "patient", "profile.wearable.import", patient_id_of(user))
    return profile.get_profile(fhir, patient_id_of(user))


@router.delete("/profile", response_model=M.ProfileOut)
def wipe_profile(user: User = Depends(patient_user), db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    profile.wipe(fhir, patient_id_of(user))
    audit.record(db, user.id, "patient", "profile.wipe", patient_id_of(user))
    return profile.get_profile(fhir, patient_id_of(user))


# ---- intake ----------------------------------------------------------------------------------
@router.post("/intakes", response_model=M.IntakeOut)
def start_intake(body: M.StartIntakeIn, user: User = Depends(patient_user), db: Session = Depends(get_db),
                 fhir: FhirStore = Depends(fhir_dep)):
    try:
        return intake_out(intake.start_or_resume(db, fhir, user, patient_id_of(user), body.lang))
    except IntakeError as e:
        raise _intake_error(e)


@router.get("/intakes/{sid}", response_model=M.IntakeOut)
def get_intake(sid: str, user: User = Depends(patient_user), db: Session = Depends(get_db)):
    return intake_out(_own_session(db, user, sid))


@router.post("/intakes/{sid}/messages", response_model=M.IntakeOut)
def post_message(sid: str, body: M.MessageIn, user: User = Depends(patient_user), db: Session = Depends(get_db),
                 fhir: FhirStore = Depends(fhir_dep)):
    s = _own_session(db, user, sid)
    try:
        return intake_out(intake.post_message(db, fhir, user, s, body.text, body.mode))
    except IntakeError as e:
        raise _intake_error(e)


@router.get("/intakes/{sid}/summary", response_model=M.SummaryOut)
def get_summary(sid: str, user: User = Depends(patient_user), db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    try:
        return intake.summary(db, fhir, _own_session(db, user, sid))
    except IntakeError as e:
        raise _intake_error(e)


@router.post("/intakes/{sid}/confirm", response_model=M.IntakeOut)
def confirm(sid: str, body: M.ConfirmIn, user: User = Depends(patient_user), db: Session = Depends(get_db),
            fhir: FhirStore = Depends(fhir_dep)):
    try:
        return intake_out(intake.confirm(db, fhir, user, _own_session(db, user, sid), body.truthful, body.correction))
    except IntakeError as e:
        raise _intake_error(e)


@router.delete("/intakes/{sid}", status_code=204)
def discard_draft(sid: str, user: User = Depends(patient_user), db: Session = Depends(get_db)):
    """Drafts (not yet confirmed) are deletable. Confirmed intakes are medical documentation."""
    s = _own_session(db, user, sid)
    if s.state in ("SUBMITTED", "CONFIRMED_BY_PATIENT", "EMERGENCY"):
        raise HTTPException(409, "This intake is part of your medical record")
    session_cache.discard(s.id)
    db.delete(s)
    db.commit()
    audit.record(db, user.id, "patient", "intake.discard", patient_id_of(user), f"IntakeSession/{sid}")
    return Response(status_code=204)


# ---- daily check-ins -----------------------------------------------------------------------------
def _checkin_state(fhir: FhirStore, pid: str, lang: str, emergency: str | None = None) -> M.CheckinStateOut:
    plan = checkins.active_plan(fhir, pid)
    if not plan:
        return M.CheckinStateOut(enabled=False, today=today().isoformat())
    t = trends.build(fhir, pid)
    done = any(p["date"] == today().isoformat() and p["ref"] for p in (t or {}).get("series", []))
    return M.CheckinStateOut(enabled=True, planTitle=plan.get("title"), since=(plan.get("period") or {}).get("start"),
                             today=today().isoformat(), todayDone=done,
                             questionnaire=checkins.definition(checkins.plan_questionnaire(plan), lang),
                             followUp=brief_service.follow_up_view(t), emergency=emergency)


@router.get("/checkins", response_model=M.CheckinStateOut)
def get_checkins(lang: str = "en", user: User = Depends(patient_user), fhir: FhirStore = Depends(fhir_dep)):
    return _checkin_state(fhir, patient_id_of(user), "pl" if lang == "pl" else "en")


@router.post("/checkins", response_model=M.CheckinStateOut)
def post_checkin(body: M.CheckinIn, user: User = Depends(patient_user), db: Session = Depends(get_db),
                 fhir: FhirStore = Depends(fhir_dep)):
    try:
        res = checkins.submit(db, fhir, user, patient_id_of(user), body.answers, body.lang)
    except CheckinError as e:
        raise HTTPException(e.status, e.message)
    return _checkin_state(fhir, patient_id_of(user), body.lang, emergency=res["emergency"])
