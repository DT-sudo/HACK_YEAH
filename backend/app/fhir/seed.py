"""Synthetic demo data (Synthea-style FHIR R4 resources). No real patient data, including the team's own.

Clinic: Przychodnia Rodzinna Kazimierz, Kraków. Demo day: Monday 5 October 2026.
Each patient also has records that are irrelevant to the complaint, so the relevance filter has
something to leave out (data minimisation is visible in the brief footer).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import CareAssignment, IntakeSession, UrgentFlag, User
from app.fhir.client import FhirStore
from app.fhir.describe import EXT_OUTCOME, WEARABLE_SYSTEM
from app.llm.gateway import LLMGateway
from app.services import brief as brief_service, profile
from app.services.profile import lifestyle_observation, medication_statement

CLINIC = "Przychodnia Rodzinna Kazimierz"
ATC = "http://www.whocc.no/atc"
ICD10 = "http://hl7.org/fhir/sid/icd-10"
LOINC = "http://loinc.org"
DAY = "2026-10-05"

DOCTORS = [
    ("ewa", "Dr. Ewa Wiśniewska", "pr-ewa"),
    ("adam", "Dr. Adam Mazur", "pr-adam"),
]
# login, given, family, gender, birthDate, fake PESEL, doctor, time, demo suggestion
PATIENTS = [
    ("marek", "Marek", "Zieliński", "male", "1965-02-11", "65021100000", "ewa", "08:00", None),
    ("halina", "Halina", "Dąbrowska", "female", "1952-07-30", "52073000000", "ewa", "08:20", "I get dizzy when I stand up"),
    ("piotr", "Piotr", "Nowak", "male", "1992-04-19", "92041900000", "ewa", "09:00", "My right knee hurts at the front when I run"),
    ("zofia", "Zofia", "Lewandowska", "female", "1997-01-08", "97010800000", "ewa", "09:20", "I've had headaches most mornings"),
    ("anna", "Anna", "Kowalska", "female", "1974-03-14", "74031400000", "ewa", "10:20", "I've had a dry cough for a few weeks"),
    ("tomasz", "Tomasz", "Wójcik", "male", "1981-11-02", "81110200000", "ewa", "11:00", "My lower back hurts after work"),
    ("jan", "Jan", "Kamiński", "male", "1958-05-21", "58052100000", "adam", "09:40", None),
]
PID = {"anna": "anna-k", "piotr": "piotr-n", "marek": "marek-z", "halina": "halina-d", "zofia": "zofia-l",
       "tomasz": "tomasz-w", "jan": "jan-k"}


REASONS = {"Condition/c-221": "Essential hypertension", "Condition/c-160": "Hypercholesterolaemia",
           "Condition/c-m-01": "Type 2 diabetes", "Condition/c-h-01": "Essential hypertension",
           "Condition/c-j-01": "Atrial fibrillation"}


def _subj(pid: str) -> dict:
    return {"reference": f"Patient/{pid}"}


def med_request(rid, pid, atc, display, text, dose, authored, status="active", reason_ref=None, reason_text=None,
                end=None, requester="Dr. Ewa Wiśniewska"):
    r = {"resourceType": "MedicationRequest", "id": rid, "status": status, "intent": "order",
         "medicationCodeableConcept": {"coding": [{"system": ATC, "code": atc, "display": display}], "text": text},
         "subject": _subj(pid), "authoredOn": authored, "requester": {"reference": "Practitioner/pr-ewa", "display": requester},
         "dosageInstruction": [{"text": dose}]}
    if reason_ref:
        r["reasonReference"] = [{"reference": reason_ref, "display": REASONS.get(reason_ref, "")}]
    if reason_text:
        r["reasonCode"] = [{"text": reason_text}]
    if end:
        r["dispenseRequest"] = {"validityPeriod": {"start": authored, "end": end}}
    return r


def condition(rid, pid, code, display, onset, status="active", recorder="Dr. Ewa Wiśniewska"):
    return {"resourceType": "Condition", "id": rid, "subject": _subj(pid),
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": status}]},
            "code": {"coding": [{"system": ICD10, "code": code, "display": display}], "text": display},
            "onsetDateTime": onset, "recordedDate": onset, "recorder": {"display": recorder}}


def encounter(rid, pid, when, reason, outcome, who="Dr. Ewa Wiśniewska"):
    return {"resourceType": "Encounter", "id": rid, "status": "finished",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"}, "subject": _subj(pid),
            "period": {"start": when}, "reasonCode": [{"text": reason}],
            "participant": [{"individual": {"reference": "Practitioner/pr-ewa", "display": who}}],
            "extension": [{"url": EXT_OUTCOME, "valueString": outcome}]}


def docref(rid, pid, when, title, description, author):
    return {"resourceType": "DocumentReference", "id": rid, "status": "current", "subject": _subj(pid),
            "type": {"text": title}, "date": when, "description": description, "author": [{"display": author}],
            "content": [{"attachment": {"contentType": "text/plain", "title": title}}]}


def allergy(rid, pid, substance, reaction, recorded, criticality="low"):
    return {"resourceType": "AllergyIntolerance", "id": rid, "patient": _subj(pid),
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]},
            "code": {"text": substance}, "criticality": criticality, "recordedDate": recorded,
            "reaction": [{"manifestation": [{"text": reaction}]}]}


def lab(rid, pid, loinc, display, value, unit, low, high, when):
    flag = "H" if value > high else "L" if value < low else "N"
    return {"resourceType": "Observation", "id": rid, "status": "final", "subject": _subj(pid),
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
            "code": {"coding": [{"system": LOINC, "code": loinc, "display": display}], "text": display},
            "valueQuantity": {"value": value, "unit": unit}, "effectiveDateTime": when,
            "referenceRange": [{"low": {"value": low, "unit": unit}, "high": {"value": high, "unit": unit}}],
            "interpretation": [{"coding": [{"code": flag, "display": {"H": "High", "L": "Low", "N": "Normal"}[flag]}]}]}


def vital(rid, pid, when, sys_, dia):
    return {"resourceType": "Observation", "id": rid, "status": "final", "subject": _subj(pid),
            "category": [{"coding": [{"code": "vital-signs"}]}],
            "code": {"coding": [{"system": LOINC, "code": "85354-9", "display": "Blood pressure panel"}], "text": "Blood pressure"},
            "effectiveDateTime": when,
            "component": [{"code": {"text": "Systolic"}, "valueQuantity": {"value": sys_, "unit": "mmHg"}},
                          {"code": {"text": "Diastolic"}, "valueQuantity": {"value": dia, "unit": "mmHg"}}]}


def wearable_summary(rid, pid, when, steps, rhr, sleep):
    return {"resourceType": "Observation", "id": rid, "status": "final", "subject": _subj(pid), "performer": [_subj(pid)],
            "category": [{"coding": [{"code": "activity"}]}],
            "code": {"coding": [{"system": WEARABLE_SYSTEM, "code": "weekly-summary"}], "text": "Wearable weekly summary"},
            "effectiveDateTime": when,
            "component": [{"code": {"text": "Steps per day (7-day average)"}, "valueQuantity": {"value": steps, "unit": "steps"}},
                          {"code": {"text": "Resting heart rate"}, "valueQuantity": {"value": rhr, "unit": "bpm"}},
                          {"code": {"text": "Sleep (average)"}, "valueQuantity": {"value": sleep, "unit": "h"}}]}


def running_series(rid, pid, weeks: list[tuple[str, float]], start, end):
    return {"resourceType": "Observation", "id": rid, "status": "final", "subject": _subj(pid), "performer": [_subj(pid)],
            "category": [{"coding": [{"code": "activity"}]}],
            "code": {"coding": [{"system": WEARABLE_SYSTEM, "code": "running-weekly"}], "text": "Running distance per week (wearable)"},
            "effectivePeriod": {"start": start, "end": end},
            "component": [{"code": {"text": w}, "valueQuantity": {"value": v, "unit": "km"}} for w, v in weeks]}


def life(pid, slug, key, value, when):
    return lifestyle_observation(pid, key, value, when, rid=f"obs-{slug}-{key}")


def appointment(rid, pid, name, doctor_ref, doctor_name, time_):
    hh, mm = map(int, time_.split(":"))
    end_m = hh * 60 + mm + 20
    return {"resourceType": "Appointment", "id": rid, "status": "booked",
            "serviceType": [{"text": "Family doctor · in person"}],
            "start": f"{DAY}T{time_}:00+02:00", "end": f"{DAY}T{end_m // 60:02d}:{end_m % 60:02d}:00+02:00",
            "participant": [{"actor": {"reference": f"Patient/{pid}", "display": name}, "status": "accepted"},
                            {"actor": {"reference": doctor_ref, "display": doctor_name}, "status": "accepted"}]}


def clinical_records() -> list[dict]:
    a, p, m, h, z, t, j = (PID[k] for k in ("anna", "piotr", "marek", "halina", "zofia", "tomasz", "jan"))
    R = [
        # ---------------- Anna Kowalska, 52: dry cough ----------------
        med_request("mr-4471", a, "C09AA03", "lisinopril", "Lisinopril 10 mg tablet", "10 mg once daily, morning", "2026-08-14",
                    reason_ref="Condition/c-221"),
        med_request("mr-3920", a, "C10AA05", "atorvastatin", "Atorvastatin 20 mg tablet", "20 mg once daily, evening", "2023-03-02",
                    reason_ref="Condition/c-160"),
        med_request("mr-4102", a, "J01CA04", "amoxicillin", "Amoxicillin 500 mg capsule", "500 mg three times daily, 7 days",
                    "2026-01-10", status="completed", reason_text="Acute sinusitis", end="2026-01-17"),
        condition("c-221", a, "I10", "Essential (primary) hypertension", "2026-08-14"),
        condition("c-160", a, "E78.0", "Pure hypercholesterolaemia", "2023-03-02"),
        condition("c-301", a, "J01.9", "Acute sinusitis", "2026-01-10", status="resolved"),
        encounter("enc-1874", a, "2025-02-03", "Cough following upper respiratory infection (URTI)",
                  "Resolved within 10 days (phone follow-up 14 Feb 2025)"),
        encounter("enc-2301", a, "2026-01-10", "Sinus pain and congestion", "Amoxicillin 7 days; resolved"),
        encounter("enc-2398", a, "2026-08-14", "Blood pressure check", "Hypertension recorded; lisinopril started"),
        encounter("enc-0911", a, "2023-06-20", "Skin check, mole on left shoulder", "Benign appearance; no follow-up"),
        docref("doc-552", a, "2025-02-05", "Chest X-ray report", "No focal consolidation. Heart size normal.", "Radiology, partner lab"),
        allergy("al-090", a, "House dust mite", "Rhinitis, mild", "2019-05-11"),
        lab("obs-a-lip", a, "2093-3", "Total cholesterol", 5.9, "mmol/L", 0, 5.0, "2026-02-03"),
        vital("obs-a-bp1", a, "2026-08-14", 152, 94),
        vital("obs-a-bp2", a, "2026-09-11", 138, 86),
        medication_statement(a, "Ibuprofen", "400 mg", "as needed, about twice a week", start="2025", asserted="2026-09-20",
                             note="Over the counter", rid="ms-a01"),
        medication_statement(a, "Vitamin D3 2000 IU", "2000 IU", "once daily", start="2025-10-01", asserted="2026-09-20",
                             reason="Supplement", rid="ms-a02"),
        medication_statement(a, "Omeprazole", "20 mg", "once daily", start="2026-06-12", asserted="2026-09-20",
                             prescriber="Another provider (private practice, Kraków)", rid="ms-a03"),
        life(a, "a", "smoking", "Former smoker, 12 pack-years, quit 2019. No vaping.", "2026-05-12"),
        life(a, "a", "alcohol", "A glass of wine at weekends, about 2 units a week", "2026-05-12"),
        life(a, "a", "activity", "Walks to work and back, about 30 minutes a day", "2026-05-12"),
        life(a, "a", "sleep", "About 6 h 40 min, regular bedtime", "2026-05-12"),
        life(a, "a", "diet", "Mixed diet, trying to eat less salt", "2026-05-12"),
        life(a, "a", "occupation", "Accountant, mostly sitting, no shifts, moderate stress", "2025-11-10"),
        wearable_summary("obs-a-wear", a, "2026-10-01", 5800, 68, 6.7),

        # ---------------- Piotr Nowak, 34: knee pain ----------------
        encounter("enc-2210", p, "2024-06-18", "Right ankle sprain, grade I, during running", "Physiotherapy referral"),
        encounter("enc-1702", p, "2025-09-12", "Occupational health check", "Fit for work; bloods taken"),
        lab("obs-p-lab", p, "2160-0", "Creatinine", 0.98, "mg/dL", 0.70, 1.20, "2025-09-12"),
        lab("obs-p-alt", p, "1742-6", "ALT", 24, "U/L", 0, 41, "2025-09-12"),
        medication_statement(p, "Ibuprofen", "400 mg", "three times daily", start="2026-09-25", asserted="2026-10-03",
                             note="Over the counter", reason="Knee pain", rid="ms-p01"),
        medication_statement(p, "Creatine monohydrate", "5 g", "once daily", start="2026-07", asserted="2026-10-03",
                             reason="Supplement", rid="ms-p02"),
        running_series("obs-p-run", p, [("24 Aug", 14), ("31 Aug", 19), ("7 Sep", 24), ("14 Sep", 29), ("21 Sep", 33), ("28 Sep", 38)],
                       "2026-08-24", "2026-10-02"),
        wearable_summary("obs-p-wear", p, "2026-10-02", 11200, 52, 7.1),
        life(p, "p", "smoking", "Never smoked", "2026-03-01"),
        life(p, "p", "alcohol", "Rarely, a beer once or twice a month", "2026-03-01"),
        life(p, "p", "activity", "Running 4 times a week, training for a half-marathon on 25 Oct", "2026-09-28"),
        life(p, "p", "sleep", "About 7 hours, rotating shifts make it irregular", "2026-03-01"),
        life(p, "p", "diet", "High protein, no restrictions", "2026-03-01"),
        life(p, "p", "occupation", "Warehouse team lead: physical work, on feet most of the shift, rotating shifts", "2026-03-01"),

        # ---------------- Marek Zieliński, 61: safety-net case ----------------
        condition("c-m-01", m, "E11.9", "Type 2 diabetes mellitus", "2021-05-04"),
        med_request("mr-m-01", m, "A10BA02", "metformin", "Metformin 1000 mg tablet", "1000 mg twice daily", "2021-05-04",
                    reason_ref="Condition/c-m-01"),
        lab("obs-m-hba1c", m, "4548-4", "HbA1c", 7.4, "%", 4.0, 6.0, "2026-06-02"),
        life(m, "m", "smoking", "Current smoker, about 10 a day", "2026-02-10"),

        # ---------------- Halina Dąbrowska, 74 ----------------
        condition("c-h-01", h, "I10", "Essential (primary) hypertension", "2015-09-01"),
        med_request("mr-h-01", h, "C08CA01", "amlodipine", "Amlodipine 5 mg tablet", "5 mg once daily", "2015-09-01",
                    reason_ref="Condition/c-h-01"),
        med_request("mr-h-02", h, "C07AB07", "bisoprolol", "Bisoprolol 2.5 mg tablet", "2.5 mg once daily", "2026-07-20",
                    reason_text="Palpitations"),
        encounter("enc-h-01", h, "2026-07-20", "Palpitations", "ECG: sinus rhythm; bisoprolol started"),

        # ---------------- Zofia Lewandowska, 29 ----------------
        encounter("enc-z-01", z, "2025-11-04", "Headache after screen work", "Advice on breaks; resolved"),
        life(z, "z", "sleep", "5–6 hours, irregular", "2026-09-30"),
        life(z, "z", "occupation", "UX designer, 9+ hours at a screen", "2026-09-30"),
        life(z, "z", "alcohol", "Occasionally at weekends", "2026-09-30"),

        # ---------------- Tomasz Wójcik, 45 ----------------
        encounter("enc-t-01", t, "2025-03-15", "Lower back pain after lifting", "Resolved with physiotherapy"),
        life(t, "t", "occupation", "Delivery driver, lifting parcels", "2025-12-01"),

        # ---------------- Jan Kamiński, 68 (Dr. Mazur's patient: break-glass demo) ----------------
        condition("c-j-01", j, "I48.9", "Atrial fibrillation", "2024-02-11"),
        med_request("mr-j-01", j, "B01AF02", "apixaban", "Apixaban 5 mg tablet", "5 mg twice daily", "2024-02-11",
                    reason_ref="Condition/c-j-01", requester="Dr. Adam Mazur"),
    ]
    return R


# Seeded confirmed intake for Piotr (via voice), so the doctor has a brief before any live demo.
PIOTR_ANSWERS = [
    {"slot": "complaint", "label": "Reason for visit", "value": "My right knee hurts at the front, especially when I run and going down stairs", "verbatim": True},
    {"slot": "location", "label": "Location", "value": "Front, around the kneecap"},
    {"slot": "onset", "label": "Onset", "value": "1–2 weeks ago"},
    {"slot": "mechanism", "label": "How it started", "value": "Came on gradually"},
    {"slot": "character", "label": "Character", "value": "Dull ache"},
    {"slot": "aggravating", "label": "Worse with", "value": "Running, Going down stairs, Sitting for a long time"},
    {"slot": "swelling", "label": "Swelling, locking, giving way", "value": "Swelling"},
    {"slot": "activity_change", "label": "Activity change", "value": "Increased my training"},
    {"slot": "relief", "label": "Relief", "value": "Painkillers help a bit"},
    {"slot": "severity", "label": "Impact (0–10)", "value": "7"},
]
ZOFIA_TRANSCRIPT = [
    {"from": "ai", "text": "Hi Zofia. In your own words, what would you like to talk to Dr. Ewa Wiśniewska about?"},
    {"from": "me", "text": "I've had headaches most mornings for a couple of weeks", "mode": "text"},
    {"from": "ai", "text": "What does the headache feel like?"},
]


def seed(db: Session, fhir: FhirStore) -> None:
    fhir.reset()
    fhir.create({"resourceType": "Organization", "id": "org-kazimierz", "name": CLINIC,
                 "address": [{"line": ["ul. Józefa 14"], "city": "Kraków", "postalCode": "31-056", "country": "PL"}],
                 "telecom": [{"system": "phone", "value": "+48 12 000 00 00"}]})
    for login, name, prid in DOCTORS:
        fhir.create({"resourceType": "Practitioner", "id": prid, "name": [{"text": name}]})
        db.add(User(id=login, role="doctor", display_name=name, fhir_ref=f"Practitioner/{prid}"))
    for login, given, family, gender, birth, pesel, doc, time_, hint in PATIENTS:
        pid = PID[login]
        fhir.create({"resourceType": "Patient", "id": pid, "name": [{"given": [given], "family": family}], "gender": gender,
                     "birthDate": birth, "identifier": [{"system": "urn:oid:2.16.840.1.113883.3.4424.1.1.616", "value": pesel}],
                     "address": [{"city": "Kraków", "country": "PL"}], "managingOrganization": {"reference": "Organization/org-kazimierz"},
                     "telecom": [{"system": "phone", "value": "+48 600 000 000"}]})
        doctor_name, prid = next((n, p) for l, n, p in DOCTORS if l == doc)
        fhir.create(appointment(f"apt-{pid}", pid, f"{given} {family}", f"Practitioner/{prid}", doctor_name, time_))
        db.add(User(id=login, role="patient", display_name=f"{given} {family}", fhir_ref=f"Patient/{pid}", demo_hint=hint))
        db.add(CareAssignment(doctor_id=doc, patient_id=pid))
    for r in clinical_records():
        fhir.create(r)
    db.commit()

    # Piotr: confirmed voice intake + brief generated through the real pipeline.
    ts = datetime.fromisoformat(f"2026-10-04T19:12:00")
    sp = IntakeSession(id="in-piotr-seed", patient_id="piotr-n", appointment_id="apt-piotr-n", state="COMPLETED", lang="en",
                       category="musculoskeletal", transcript=[], answers=PIOTR_ANSWERS, current_question=None,
                       question_count=9, flags={}, created_at=ts, updated_at=ts)
    db.add(sp)
    db.commit()
    qr = fhir.create({"resourceType": "QuestionnaireResponse", "id": "qr-p-1005", "status": "completed",
                      "questionnaire": "Questionnaire/vc-intake-v1", "subject": _subj("piotr-n"), "source": _subj("piotr-n"),
                      "authored": "2026-10-04T19:12:00+02:00",
                      "item": [{"linkId": a["slot"], "text": a["label"], "answer": [{"valueString": a["value"]}]} for a in PIOTR_ANSWERS],
                      "extension": [{"url": "https://vitalcontext.example/fhir/StructureDefinition/intake-mode",
                                     "valueString": "AI-guided chat, voice"}]})
    # Seeded briefs always use the deterministic provider, so the demo starts identical every time.
    comp, refs = brief_service.generate(db, fhir, sp, f"QuestionnaireResponse/{qr['id']}", gateway=LLMGateway(provider="mock"),
                                        composition_id="brief-p-1005", created="2026-10-04T19:13:00")
    profile.mark_documented(fhir, refs)
    sp.questionnaire_response_id, sp.brief_id, sp.state = qr["id"], comp["id"], "SUBMITTED"

    # Marek: stopped by the safety net this morning.
    tm = datetime.fromisoformat("2026-10-05T07:42:00")
    db.add(IntakeSession(id="in-marek-seed", patient_id="marek-z", appointment_id="apt-marek-z", state="EMERGENCY", lang="pl",
                         category=None, transcript=[
                             {"from": "ai", "text": "Dzień dobry, Marek. Proszę opisać własnymi słowami, z czym zgłasza się Pan/Pani na wizytę (Dr. Ewa Wiśniewska)."},
                             {"from": "me", "text": "Od rana mam ból w klatce piersiowej i drętwieje mi lewa ręka", "mode": "voice"}],
                         answers=[], current_question=None, question_count=0,
                         flags={"red_flag": {"rule_id": "chest_pain", "label": "Chest pain or pressure"}}, created_at=tm, updated_at=tm))
    db.add(UrgentFlag(patient_id="marek-z", session_id="in-marek-seed", appointment_id="apt-marek-z", rule_id="chest_pain",
                      trigger_text='Chest pain or pressure. Patient said: "Od rana mam ból w klatce piersiowej i drętwieje mi lewa ręka" '
                                   '(this morning I have chest pain and my left arm is going numb)', created_at=tm))

    # Zofia: still answering.
    tz = datetime.fromisoformat("2026-10-05T07:55:00")
    db.add(IntakeSession(id="in-zofia-seed", patient_id="zofia-l", appointment_id="apt-zofia-l", state="COLLECTING", lang="en",
                         category="headache", transcript=ZOFIA_TRANSCRIPT,
                         answers=[{"slot": "complaint", "label": "Reason for visit", "value": ZOFIA_TRANSCRIPT[1]["text"], "verbatim": True},
                                  {"slot": "onset", "label": "Onset", "value": "1–2 weeks ago"}],
                         current_question={"slot": "character", "label": "Character", "text": "What does the headache feel like?",
                                           "answer_type": "single", "options": ["Throbbing", "Pressing or tight", "Stabbing", "Hard to describe"]},
                         question_count=1, flags={}, created_at=tz, updated_at=tz))
    db.commit()
