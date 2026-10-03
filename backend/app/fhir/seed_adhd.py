"""Synthetic ADHD follow-up scenario (target group: tech-literate adults 25-40 managing a newly
diagnosed condition between visits). Psychiatry day for Dr. Marta Kaczmarek, Monday 5 Oct 2026.

Natalia Zając (28) is the live demo patient: methylphenidate ER titrated 18 -> 27 mg on 17 Sep,
27 days of daily check-ins and wearable aggregates, pre-visit chat not done yet.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import CareAssignment, IntakeSession, UrgentFlag, User
from app.fhir.client import FhirStore
from app.fhir.describe import WEARABLE_SYSTEM
from app.services import checkins
from app.services.profile import lifestyle_observation, medication_statement

DOCTOR = ("marta", "Dr. Marta Kaczmarek", "pr-marta")
SERVICE = "Psychiatry follow-up · in person"
QID = "vc-daily-adhd-v1"

# login, pid, given, family, gender, birth, pesel, time, demo hint
PATIENTS = [
    ("kamila", "kamila-n", "Kamila", "Nowicka", "female", "2000-03-02", "00230200000", "09:00", None),
    ("natalia", "natalia-z", "Natalia", "Zając", "female", "1998-06-11", "98061100000", "09:30",
     "Focus is much better on the higher dose, but it wears off in the afternoon and I sleep badly"),
    ("bartosz", "bartosz-k", "Bartosz", "Kowal", "male", "1992-01-25", "92012500000", "10:15", None),
    ("michal", "michal-g", "Michał", "Grabowski", "male", "1995-09-30", "95093000000", "11:00",
     "Things are mostly fine, I'd like to talk about the evenings"),
]


def _subj(pid: str) -> dict:
    return {"reference": f"Patient/{pid}"}


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _days(start: str, end: str) -> list[str]:
    a, b = _d(start), _d(end)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def condition(rid, pid, code, display, onset):
    return {"resourceType": "Condition", "id": rid, "subject": _subj(pid),
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": code, "display": display}], "text": display},
            "onsetDateTime": onset, "recordedDate": onset, "recorder": {"display": DOCTOR[1]}}


def mph(rid, pid, mg, start, cond, end=None):
    r = {"resourceType": "MedicationRequest", "id": rid, "status": "completed" if end else "active", "intent": "order",
         "medicationCodeableConcept": {"coding": [{"system": "http://www.whocc.no/atc", "code": "N06BA04", "display": "methylphenidate"}],
                                       "text": f"Methylphenidate ER {mg} mg tablet"},
         "subject": _subj(pid), "authoredOn": start,
         "requester": {"reference": "Practitioner/pr-marta", "display": DOCTOR[1]},
         "dosageInstruction": [{"text": f"{mg} mg once daily, morning"}],
         "reasonReference": [{"reference": f"Condition/{cond}", "display": "ADHD"}]}
    if end:
        r["dispenseRequest"] = {"validityPeriod": {"start": start, "end": end}}
    return r


def encounter(rid, pid, when, reason, outcome, who=DOCTOR[1]):
    from app.fhir.describe import EXT_OUTCOME
    return {"resourceType": "Encounter", "id": rid, "status": "finished",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"}, "subject": _subj(pid),
            "period": {"start": when}, "reasonCode": [{"text": reason}],
            "participant": [{"individual": {"display": who}}],
            "extension": [{"url": EXT_OUTCOME, "valueString": outcome}]}


def vitals(rid, pid, when, sys_, dia, hr):
    return [
        {"resourceType": "Observation", "id": f"{rid}-bp", "status": "final", "subject": _subj(pid),
         "category": [{"coding": [{"code": "vital-signs"}]}],
         "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}], "text": "Blood pressure"},
         "effectiveDateTime": when,
         "component": [{"code": {"text": "Systolic"}, "valueQuantity": {"value": sys_, "unit": "mmHg"}},
                       {"code": {"text": "Diastolic"}, "valueQuantity": {"value": dia, "unit": "mmHg"}}]},
        {"resourceType": "Observation", "id": f"{rid}-hr", "status": "final", "subject": _subj(pid),
         "category": [{"coding": [{"code": "vital-signs"}]}],
         "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}], "text": "Heart rate"},
         "effectiveDateTime": when, "valueQuantity": {"value": hr, "unit": "bpm"}},
    ]


def ecg(rid, pid, when, finding):
    return {"resourceType": "DocumentReference", "id": rid, "status": "current", "subject": _subj(pid),
            "type": {"text": "ECG before starting stimulant"}, "date": f"{when}T10:00:00+02:00", "description": finding,
            "author": [{"display": "Cardiology lab, Centrum Medyczne Kazimierz"}],
            "content": [{"attachment": {"contentType": "text/plain", "title": "ECG report"}}]}


def care_plan(rid, pid, cond, start):
    return {"resourceType": "CarePlan", "id": rid, "status": "active", "intent": "plan", "subject": _subj(pid),
            "title": "Daily check-ins until the follow-up visit", "period": {"start": start},
            "addresses": [{"reference": f"Condition/{cond}"}], "author": {"reference": "Practitioner/pr-marta", "display": DOCTOR[1]},
            "activity": [{"detail": {"status": "in-progress", "kind": "Task",
                                     "instantiatesCanonical": [f"{checkins.VC_Q}/{QID}"],
                                     "description": "About one minute a day: medicine, focus, sleep, appetite, side effects."}}]}


def daily_obs(rid, pid, kind, label, unit, values: dict[str, float]):
    days = sorted(values)
    return {"resourceType": "Observation", "id": rid, "status": "final", "subject": _subj(pid), "performer": [_subj(pid)],
            "category": [{"coding": [{"code": "activity"}]}],
            "code": {"coding": [{"system": WEARABLE_SYSTEM, "code": kind}], "text": label},
            "effectivePeriod": {"start": days[0], "end": days[-1]},
            "component": [{"code": {"text": d}, "valueQuantity": {"value": values[d], "unit": unit}} for d in days]}


def checkin_qr(pid: str, plan: dict, day: str, a: dict) -> dict:
    items = checkins.validate(QID, a)
    qr = checkins.build_qr(pid, plan, items, f"{day}T20:{(len(day) * 7) % 60:02d}:00+02:00", rid=f"chk-{pid}-{day}")
    return qr


def _row(med, focus, lost, trig, sleep, app, side, note=None):
    a = {"med_taken": med, "focus": focus, "focus_lost": lost, "triggers": trig, "sleep": sleep, "appetite": app,
         "side_effects": side}
    if note:
        a["note"] = note
    return a


# Natalia: 9 days on 18 mg, then 18 days on 27 mg (from 17 Sep). Hand-written so the story is stable.
NATALIA = [
    # 18 mg
    _row("on_time", 4, ["early_afternoon"], ["phone", "meetings"], "7.5", "normal", ["none"]),
    _row("on_time", 3, ["morning", "early_afternoon"], ["phone", "noise"], "6.5", "normal", ["none"]),
    _row("on_time", 5, ["early_afternoon"], ["meetings"], "7.5", "normal", ["headache"]),
    _row("late", 4, ["morning"], ["phone"], "6.5", "normal", ["none"]),
    _row("on_time", 4, ["early_afternoon"], ["meetings", "phone"], "7.5", "lower", ["none"]),
    _row("on_time", 5, ["early_afternoon"], ["noise"], "6.5", "normal", ["none"],
         "Started the day well, lost it after lunch."),
    _row("on_time", 3, ["morning", "early_afternoon"], ["phone", "poor_sleep"], "5.5", "normal", ["none"]),
    _row("on_time", 4, ["early_afternoon"], ["meetings"], "7.5", "normal", ["none"]),
    _row("on_time", 5, ["early_afternoon"], ["phone"], "7.5", "normal", ["none"]),
    # 27 mg from 17 Sep
    _row("on_time", 7, ["late_afternoon"], ["meetings"], "6.5", "lower", ["insomnia"]),
    _row("on_time", 7, ["late_afternoon"], ["phone"], "5.5", "lower", ["insomnia"]),
    _row("on_time", 8, ["late_afternoon"], ["meetings"], "5.5", "skipped", ["insomnia", "racing_heart"],
         "Coffee at 4 pm to get through a deadline, couldn't fall asleep until 1 am."),
    _row("late", 6, ["late_afternoon", "evening"], ["poor_sleep"], "5.5", "lower", ["insomnia"]),
    _row("on_time", 7, ["late_afternoon"], ["meetings", "phone"], "6.5", "normal", ["none"]),
    _row("on_time", 7, ["evening"], ["phone"], "6.5", "lower", ["headache"]),
    _row("on_time", 8, ["late_afternoon"], ["meetings"], "5.5", "lower", ["insomnia"],
         "Great focus until about 3 pm, then nothing."),
    _row("on_time", 7, ["late_afternoon"], ["meetings"], "6.5", "lower", ["none"]),
    _row("on_time", 6, ["late_afternoon"], ["poor_sleep", "meetings"], "5.5", "skipped", ["insomnia", "irritability"]),
    _row("missed", 3, ["morning", "early_afternoon"], ["phone", "noise"], "7.5", "normal", ["none"]),
    _row("late", 6, ["late_afternoon"], ["poor_sleep"], "5.5", "lower", ["insomnia"]),
    _row("on_time", 7, ["late_afternoon"], ["meetings", "phone"], "5.5", "lower", ["racing_heart"]),
    _row("on_time", 8, ["evening"], ["meetings"], "6.5", "normal", ["none"]),
    _row("on_time", 7, ["late_afternoon"], ["meetings"], "5.5", "lower", ["insomnia"]),
    _row("on_time", 7, ["late_afternoon"], ["phone"], "6.5", "skipped", ["headache"], "Forgot lunch again."),
    _row("late", 6, ["late_afternoon"], ["poor_sleep", "meetings"], "5.5", "lower", ["insomnia", "racing_heart"]),
    _row("on_time", 8, ["late_afternoon"], ["meetings"], "6.5", "normal", ["none"]),
    _row("missed", 4, ["morning", "early_afternoon"], ["phone"], "7.5", "normal", ["none"]),
]
NATALIA_RHR = [63, 62, 64, 63, 65, 62, 64, 63, 62, 69, 71, 74, 72, 70, 71, 73, 70, 72, 66, 71, 74, 70, 72, 71, 73, 72, 67]
NATALIA_SLEEP_DEV = [6.9, 6.2, 7.0, 6.1, 6.8, 6.3, 5.4, 6.9, 7.1, 5.8, 5.0, 4.6, 5.1, 5.7, 5.9, 5.0, 5.8, 4.9, 6.8, 5.0,
                     5.2, 5.9, 4.8, 5.8, 4.9, 5.9, 6.9]

BARTOSZ_ANSWERS = [
    {"slot": "complaint", "label": "Reason for visit",
     "value": "Doing well overall, work is easier. Afternoons are still hard and I sometimes forget the tablet at weekends.",
     "verbatim": True},
    {"slot": "overall", "label": "Overall since the dose change", "value": "Better"},
    {"slot": "med_adherence", "label": "Medicine taken as planned", "value": "Every day"},
    {"slot": "side_effects", "label": "Noticed since the dose change", "value": "None of these"},
    {"slot": "wear_off", "label": "When the effect fades", "value": "Late afternoon"},
    {"slot": "sleep", "label": "Sleep", "value": "About the same"},
    {"slot": "work_impact", "label": "Impact on work or study (0–10)", "value": "3"},
    {"slot": "wishes", "label": "Wants to discuss", "value": "Is it OK to skip the tablet on weekends?", "verbatim": True},
]


def records() -> list[dict]:
    n, b, k, m = "natalia-z", "bartosz-k", "kamila-n", "michal-g"
    R: list[dict] = [{"resourceType": "Practitioner", "id": DOCTOR[2], "name": [{"text": DOCTOR[1]}],
                      "qualification": [{"code": {"text": "Psychiatrist"}}]}]
    # Natalia
    R += [condition("c-n-adhd", n, "F90.0", "Attention-deficit hyperactivity disorder, predominantly inattentive", "2026-08-20"),
          encounter("enc-n-gp", n, "2026-07-15", "Difficulty concentrating at work, poor sleep",
                    "Referred to psychiatry for assessment", who="Dr. Ewa Wiśniewska"),
          encounter("enc-n-dx", n, "2026-08-20", "ADHD assessment (DIVA-5, ASRS v1.1)",
                    "ADHD confirmed; methylphenidate ER 18 mg started; daily check-ins and follow-up in 6 weeks"),
          encounter("enc-n-tel", n, "2026-09-16", "Phone consultation: focus still low on 18 mg",
                    "Dose increased to 27 mg from 17 Sep"),
          mph("mr-n-mph18", n, 18, "2026-08-20", "c-n-adhd", end="2026-09-16"),
          mph("mr-n-mph27", n, 27, "2026-09-17", "c-n-adhd"),
          ecg("doc-n-ecg", n, "2026-08-18", "Sinus rhythm 64/min, QTc 412 ms, no abnormalities."),
          *vitals("obs-n-base", n, "2026-08-20", 116, 74, 64),
          medication_statement(n, "Melatonin", "3 mg", "before bed", start="2026-09-25", asserted="2026-09-25",
                               reason="Sleep", note="Over the counter", rid="ms-n-mel"),
          medication_statement(n, "Magnesium + B6", "1 tablet", "once daily", start="2026-06", asserted="2026-08-20",
                               reason="Supplement", rid="ms-n-mg"),
          lifestyle_observation(n, "occupation", "UX researcher, hybrid work, many long video meetings", "2026-08-20", rid="obs-n-occupation"),
          lifestyle_observation(n, "sleep", "About 7 hours on weekdays, often falls asleep late", "2026-08-20", rid="obs-n-sleep"),
          lifestyle_observation(n, "substances", "Coffee 3–4 cups a day; energy drink some afternoons", "2026-08-20", rid="obs-n-substances"),
          lifestyle_observation(n, "alcohol", "1–2 drinks at weekends", "2026-08-20", rid="obs-n-alcohol"),
          lifestyle_observation(n, "activity", "Bouldering twice a week", "2026-08-20", rid="obs-n-activity"),
          lifestyle_observation(n, "smoking", "Never smoked", "2026-08-20", rid="obs-n-smoking"),
          lifestyle_observation(n, "diet", "Regular meals, often skips breakfast", "2026-08-20", rid="obs-n-diet")]
    days = _days("2026-09-08", "2026-10-04")
    R += [daily_obs("obs-n-rhr", n, "rhr-daily", "Resting heart rate, daily (wearable)", "bpm", dict(zip(days, NATALIA_RHR))),
          daily_obs("obs-n-sleepdev", n, "sleep-daily", "Sleep duration, daily (wearable)", "h", dict(zip(days, NATALIA_SLEEP_DEV)))]
    # Bartosz
    R += [condition("c-b-adhd", b, "F90.2", "Attention-deficit hyperactivity disorder, combined type", "2026-05-12"),
          encounter("enc-b-dx", b, "2026-05-12", "ADHD assessment (DIVA-5)", "ADHD confirmed; methylphenidate ER 18 mg started"),
          encounter("enc-b-fu", b, "2026-07-30", "Follow-up after titration", "Dose 36 mg kept; daily check-ins before next visit"),
          mph("mr-b-mph36", b, 36, "2026-07-30", "c-b-adhd"),
          *vitals("obs-b-base", b, "2026-07-30", 124, 80, 70),
          lifestyle_observation(b, "occupation", "Backend developer, remote", "2026-05-12", rid="obs-b-occupation"),
          lifestyle_observation(b, "sleep", "7–8 hours", "2026-05-12", rid="obs-b-sleep"),
          lifestyle_observation(b, "substances", "Coffee 2 cups a day", "2026-05-12", rid="obs-b-substances")]
    bdays = _days("2026-09-21", "2026-10-04")
    R += [daily_obs("obs-b-rhr", b, "rhr-daily", "Resting heart rate, daily (wearable)", "bpm",
                    dict(zip(bdays, [71, 72, 70, 73, 72, 71, 70, 72, 74, 71, 70, 72, 73, 71]))),
          daily_obs("obs-b-sleepdev", b, "sleep-daily", "Sleep duration, daily (wearable)", "h",
                    dict(zip(bdays, [7.2, 7.4, 7.1, 6.9, 7.3, 7.8, 8.0, 7.2, 7.0, 7.3, 7.1, 7.2, 7.9, 8.1])))]
    # Kamila (safety-net case) and Michał (not started)
    R += [condition("c-k-adhd", k, "F90.0", "Attention-deficit hyperactivity disorder, predominantly inattentive", "2026-09-01"),
          mph("mr-k-mph18", k, 18, "2026-09-01", "c-k-adhd"),
          condition("c-m-adhd", m, "F90.0", "Attention-deficit hyperactivity disorder, predominantly inattentive", "2026-06-20"),
          mph("mr-m-mph27", m, 27, "2026-08-01", "c-m-adhd")]
    return R


def seed_adhd(db: Session, fhir: FhirStore, appointment) -> None:
    login, name, prid = DOCTOR
    db.add(User(id=login, role="doctor", display_name=name, fhir_ref=f"Practitioner/{prid}"))
    for login_, pid, given, family, gender, birth, pesel, time_, hint in PATIENTS:
        fhir.create({"resourceType": "Patient", "id": pid, "name": [{"given": [given], "family": family}], "gender": gender,
                     "birthDate": birth, "identifier": [{"system": "urn:oid:2.16.840.1.113883.3.4424.1.1.616", "value": pesel}],
                     "address": [{"city": "Kraków", "country": "PL"}], "managingOrganization": {"reference": "Organization/org-kazimierz"}})
        appt = appointment(f"apt-{pid}", pid, f"{given} {family}", f"Practitioner/{prid}", name, time_)
        appt["serviceType"] = [{"coding": [{"system": "https://vitalcontext.example/visit-type", "code": "adhd-followup"}], "text": SERVICE}]
        fhir.create(appt)
        db.add(User(id=login_, role="patient", display_name=f"{given} {family}", fhir_ref=f"Patient/{pid}", demo_hint=hint))
    db.flush()
    for login_, pid, *_ in PATIENTS:
        db.add(CareAssignment(doctor_id=login, patient_id=pid))
    for r in records():
        fhir.create(r)

    plans = {"natalia-z": care_plan("cp-n", "natalia-z", "c-n-adhd", "2026-09-08"),
             "bartosz-k": care_plan("cp-b", "bartosz-k", "c-b-adhd", "2026-09-21"),
             "kamila-n": care_plan("cp-k", "kamila-n", "c-k-adhd", "2026-09-29"),
             "michal-g": care_plan("cp-m", "michal-g", "c-m-adhd", "2026-09-28")}
    for p in plans.values():
        fhir.create(p)
    for day, a in zip(_days("2026-09-08", "2026-10-04"), NATALIA):
        fhir.create(checkin_qr("natalia-z", plans["natalia-z"], day, a))
    bart = [_row("on_time" if i % 7 not in (5, 6) else ("missed" if i in (6, 13) else "late"), [6, 7, 7, 6, 7, 5, 4][i % 7],
                 ["late_afternoon"], ["meetings"] if i % 2 else ["phone"], "7.5", "lower" if i in (1, 4, 8, 11) else "normal",
                 ["none"]) for i in range(14)]
    for day, a in zip(_days("2026-09-21", "2026-10-04"), bart):
        fhir.create(checkin_qr("bartosz-k", plans["bartosz-k"], day, a))
    for i, day in enumerate(_days("2026-09-28", "2026-10-04")):
        fhir.create(checkin_qr("michal-g", plans["michal-g"], day,
                               _row("on_time", [6, 7, 6, 7, 5, 6, 7][i], ["evening"], ["phone"], "6.5", "normal", ["none"])))
    for i, day in enumerate(_days("2026-09-29", "2026-10-04")):
        fhir.create(checkin_qr("kamila-n", plans["kamila-n"], day,
                               _row("on_time", [5, 6, 6, 5, 6, 6][i], ["early_afternoon"], ["noise"], "6.5", "lower",
                                    ["racing_heart"] if i >= 3 else ["none"])))
    for pid in plans:
        checkins.sync_list(fhir, pid)
    db.commit()

    # Bartosz: confirmed pre-visit chat yesterday, brief generated by the real pipeline (deterministic provider).
    from app.llm.gateway import LLMGateway
    from app.services import brief as brief_service, profile
    ts = datetime.fromisoformat("2026-10-04T21:05:00")
    sb = IntakeSession(id="in-bartosz-seed", patient_id="bartosz-k", appointment_id="apt-bartosz-k", state="COMPLETED", lang="en",
                       category="adhd_followup", transcript=[], answers=BARTOSZ_ANSWERS, current_question=None,
                       question_count=8, flags={}, created_at=ts, updated_at=ts)
    db.add(sb)
    db.commit()
    qr = fhir.create({"resourceType": "QuestionnaireResponse", "id": "qr-b-1004", "status": "completed",
                      "questionnaire": "Questionnaire/vc-intake-v1", "subject": _subj("bartosz-k"), "source": _subj("bartosz-k"),
                      "authored": "2026-10-04T21:05:00+02:00",
                      "item": [{"linkId": a["slot"], "text": a["label"], "answer": [{"valueString": a["value"]}]} for a in BARTOSZ_ANSWERS]})
    comp, refs = brief_service.generate(db, fhir, sb, f"QuestionnaireResponse/{qr['id']}", gateway=LLMGateway(provider="mock"),
                                        composition_id="brief-b-1004", created="2026-10-04T21:06:00+02:00")
    profile.mark_documented(fhir, refs)
    sb.questionnaire_response_id, sb.brief_id, sb.state = qr["id"], comp["id"], "SUBMITTED"

    # Kamila: today's check-in note tripped the safety net at 07:51.
    tk = datetime.fromisoformat("2026-10-05T07:51:00")
    db.add(UrgentFlag(patient_id="kamila-n", session_id="checkin:chk-kamila-n-2026-10-05", appointment_id="apt-kamila-n",
                      rule_id="chest_pain", created_at=tk,
                      trigger_text='Chest pain or pressure. Daily check-in note: "Tightness in my chest and racing heart '
                                   'about an hour after the tablet this morning."'))
    db.commit()
