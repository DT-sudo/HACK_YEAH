"""Doctor endpoints. Access requires a care assignment; break-glass is separate, reasoned and audited."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import models as M
from app.api.deps import assigned_patient, doctor_user, fhir_dep
from app.db.models import AuditLog, BriefReview, CareAssignment, IntakeSession, LlmCallLog, UrgentFlag, User
from app.db.session import get_db
from app.fhir.client import FhirStore
from app.fhir.describe import date_of, fields_of, source_of, title_of
from app.services import audit, brief as brief_service, intake, safety
from app.services.context import age_of
from app.settings import get_settings, iso_now, now, today

router = APIRouter(prefix="/doctor", tags=["doctor"])


def _day_entry(db: Session, fhir: FhirStore, a: CareAssignment) -> M.DayPatientOut | None:
    pid = a.patient_id
    p = fhir.read("Patient", pid)
    appt = intake.upcoming_appointment(fhir, pid)
    if not p or not appt:
        return None
    name = " ".join(p["name"][0].get("given", [])) + " " + p["name"][0].get("family", "")
    s = intake.latest_session(db, pid, appt.id)
    flag = db.scalars(select(UrgentFlag).where(UrgentFlag.patient_id == pid, UrgentFlag.appointment_id == appt.id)
                      .order_by(UrgentFlag.created_at.desc())).first()
    brief_id = s.brief_id if s and s.state == "SUBMITTED" else None
    reviewed = brief_id and db.scalars(select(BriefReview).where(BriefReview.brief_id == brief_id)).first()
    status = ("urgent" if flag else "reviewed" if reviewed else "ready" if brief_id else
              "progress" if s and s.state in ("COLLECTING", "COMPLETED", "CONFIRMED_BY_PATIENT") else "none")
    contacted_by = db.get(User, flag.contacted_by).display_name if flag and flag.contacted_by else None
    created = (fhir.read("Composition", brief_id) or {}).get("date") if brief_id else None
    fresh = bool(created) and (now() - datetime.fromisoformat(created[:19])) < timedelta(minutes=15)
    return M.DayPatientOut(
        patientId=pid, name=name, age=age_of(p.get("birthDate")), sex=p.get("gender", ""),
        time=appt.start[11:16], status=status, briefId=brief_id,
        briefCreatedAt=created, briefFresh=fresh,
        urgent=M.UrgentOut(ruleId=flag.rule_id, trigger=flag.trigger_text, at=flag.created_at.isoformat(),
                           contactedBy=contacted_by, contactedAt=flag.contacted_at.isoformat() if flag.contacted_at else None) if flag else None,
        breakGlass=a.break_glass,
    )


@router.get("/patients", response_model=M.DayOut)
def day(user: User = Depends(doctor_user), db: Session = Depends(get_db), fhir: FhirStore = Depends(fhir_dep)):
    """Today's assigned patients only (plus any active break-glass grants)."""
    rows = []
    for a in db.scalars(select(CareAssignment).where(CareAssignment.doctor_id == user.id)).all():
        if a.expires_at and a.expires_at < now():
            continue
        e = _day_entry(db, fhir, a)
        if e:
            rows.append(e)
    rows.sort(key=lambda r: (r.status != "urgent", r.time))
    audit.record(db, user.id, "doctor", "day.list")
    return M.DayOut(date=today().isoformat(), doctor=user.display_name, patients=rows)


@router.get("/patients/{pid}/briefs/{bid}", response_model=M.BriefOut)
def get_brief(bid: str, pid: str = Depends(assigned_patient), user: User = Depends(doctor_user), db: Session = Depends(get_db),
              fhir: FhirStore = Depends(fhir_dep)):
    b = brief_service.read_brief(db, fhir, pid, bid)
    if not b:
        raise HTTPException(404, "Brief not found")
    audit.record(db, user.id, "doctor", "brief.read", pid, f"Composition/{bid}")
    return b


@router.get("/patients/{pid}/briefs/{bid}/text", response_class=PlainTextResponse)
def brief_text(bid: str, pid: str = Depends(assigned_patient), user: User = Depends(doctor_user), db: Session = Depends(get_db),
               fhir: FhirStore = Depends(fhir_dep)):
    b = brief_service.read_brief(db, fhir, pid, bid)
    if not b:
        raise HTTPException(404, "Brief not found")
    p = fhir.read("Patient", pid)
    audit.record(db, user.id, "doctor", "brief.copy", pid, f"Composition/{bid}")
    return brief_service.brief_as_text(b, f"{p['name'][0]['given'][0]} {p['name'][0]['family']}")


@router.post("/patients/{pid}/briefs/{bid}/review", response_model=M.ReviewOut)
def review(bid: str, pid: str = Depends(assigned_patient), user: User = Depends(doctor_user), db: Session = Depends(get_db),
           fhir: FhirStore = Depends(fhir_dep)):
    if not brief_service.read_brief(db, fhir, pid, bid):
        raise HTTPException(404, "Brief not found")
    r = BriefReview(brief_id=bid, doctor_id=user.id, at=now())
    db.add(r)
    db.commit()
    audit.record(db, user.id, "doctor", "brief.review", pid, f"Composition/{bid}")
    return M.ReviewOut(by=user.display_name, at=r.at.isoformat())


@router.get("/patients/{pid}/sources/{ref:path}", response_model=M.SourceOut)
def source(ref: str, pid: str = Depends(assigned_patient), user: User = Depends(doctor_user), db: Session = Depends(get_db),
           fhir: FhirStore = Depends(fhir_dep)):
    """One-click verification: the original record behind a citation."""
    if "/" not in ref:
        raise HTTPException(400, "Expected Type/id")
    rt, rid = ref.split("/", 1)
    r = fhir.read(rt, rid)
    owner = (r or {}).get("subject", {}).get("reference") or (r or {}).get("patient", {}).get("reference")
    if not r or owner != f"Patient/{pid}":
        raise HTTPException(404, "Record not found for this patient")
    audit.record(db, user.id, "doctor", "source.read", pid, ref)
    return M.SourceOut(reference=ref, type=rt, source=source_of(r), title=title_of(r), date=date_of(r), fields=fields_of(r),
                       verified=True, version=(r.get("meta") or {}).get("versionId"), raw=r)


@router.post("/patients/{pid}/medications/{ref:path}/reconcile", response_model=M.ReconciledOut)
def reconcile(ref: str, pid: str = Depends(assigned_patient), user: User = Depends(doctor_user), db: Session = Depends(get_db),
              fhir: FhirStore = Depends(fhir_dep)):
    rt, _, rid = ref.partition("/")
    r = fhir.read(rt, rid) if rt in ("MedicationRequest", "MedicationStatement") else None
    if not r or r.get("subject", {}).get("reference") != f"Patient/{pid}":
        raise HTTPException(404, "Medication not found")
    prov = fhir.create({"resourceType": "Provenance", "target": [{"reference": ref}], "recorded": iso_now(),
                        "activity": {"text": "reconciled"},
                        "agent": [{"who": {"reference": user.fhir_ref, "display": user.display_name}}]})
    audit.record(db, user.id, "doctor", "medication.reconcile", pid, ref)
    return M.ReconciledOut(by=user.display_name, at=prov["recorded"][:10])


@router.post("/patients/{pid}/urgent/contacted", response_model=M.UrgentOut)
def mark_contacted(pid: str = Depends(assigned_patient), user: User = Depends(doctor_user), db: Session = Depends(get_db)):
    flag = db.scalars(select(UrgentFlag).where(UrgentFlag.patient_id == pid).order_by(UrgentFlag.created_at.desc())).first()
    if not flag:
        raise HTTPException(404, "No urgent flag")
    flag.contacted_by, flag.contacted_at = user.id, now()
    db.commit()
    audit.record(db, user.id, "doctor", "urgent.contacted", pid, f"UrgentFlag/{flag.id}")
    return M.UrgentOut(ruleId=flag.rule_id, trigger=flag.trigger_text, at=flag.created_at.isoformat(),
                       contactedBy=user.display_name, contactedAt=flag.contacted_at.isoformat())


@router.post("/break-glass/{pid}", response_model=M.DayPatientOut)
def break_glass(pid: str, body: M.BreakGlassIn, user: User = Depends(doctor_user), db: Session = Depends(get_db),
                fhir: FhirStore = Depends(fhir_dep)):
    """Emergency / substitution access to a patient without a care assignment. Reason required; always audited."""
    if not fhir.read("Patient", pid):
        raise HTTPException(404, "Patient not found")
    a = CareAssignment(doctor_id=user.id, patient_id=pid, break_glass=True, reason=body.reason,
                       expires_at=now() + timedelta(hours=8))
    db.add(a)
    db.commit()
    audit.record(db, user.id, "doctor", "break_glass", pid, reason=body.reason)
    e = _day_entry(db, fhir, a)
    if not e:
        raise HTTPException(404, "No upcoming appointment for this patient")
    return e


@router.get("/audit", response_model=list[M.AuditOut])
def audit_log(user: User = Depends(doctor_user), db: Session = Depends(get_db)):
    """Demo transparency view: the most recent audit entries (references only, no medical content)."""
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(80)).all()
    return [M.AuditOut(who=r.who, role=r.role, patientId=r.patient_id, action=r.action, resource=r.resource, reason=r.reason,
                       timestamp=r.timestamp.isoformat()) for r in rows]


@router.get("/llm-calls", response_model=list[M.LlmCallOut])
def llm_calls(user: User = Depends(doctor_user), db: Session = Depends(get_db)):
    """Gateway metadata only: task, provider, prompt version, latency, tokens, validation result."""
    rows = db.scalars(select(LlmCallLog).order_by(LlmCallLog.id.desc()).limit(60)).all()
    return [M.LlmCallOut(task=r.task, provider=r.provider, promptVersion=r.prompt_version, latencyMs=r.latency_ms,
                         inputTokens=r.input_tokens, outputTokens=r.output_tokens, validation=r.validation,
                         timestamp=r.timestamp.isoformat()) for r in rows]
