"""Daily check-ins between visits. Fixed questionnaires (config/checkins.yaml), no AI.

* Enabled per patient by a clinician-owned FHIR CarePlan.
* Each day's answers are one QuestionnaireResponse (re-submitting the same day updates it).
* A FHIR List per patient collects them, so the brief can cite "all check-ins" with one reference.
* Free text and answers go through the same deterministic red-flag rules as the intake chat.
"""
from __future__ import annotations

from functools import lru_cache

import yaml
from sqlalchemy.orm import Session

from app.db.models import UrgentFlag, User
from app.fhir.client import FhirStore
from app.services import audit, safety
from app.settings import CONFIG_DIR, iso_now, now, today

VC_Q = "https://vitalcontext.example/fhir/Questionnaire"


class CheckinError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


@lru_cache
def questionnaires() -> dict:
    return yaml.safe_load((CONFIG_DIR / "checkins.yaml").read_text(encoding="utf-8"))["questionnaires"]


def active_plan(fhir: FhirStore, patient_id: str) -> dict | None:
    plans = [p for p in fhir.search("CarePlan", patient=f"Patient/{patient_id}") if p.get("status") == "active"]
    return sorted(plans, key=lambda p: (p.get("period") or {}).get("start", ""))[-1] if plans else None


def plan_questionnaire(plan: dict) -> str:
    canon = (plan.get("activity") or [{}])[0].get("detail", {}).get("instantiatesCanonical", [""])[0]
    return canon.rsplit("/", 1)[-1]


def definition(qid: str, lang: str) -> dict:
    q = questionnaires()[qid]
    pick = lambda d: d.get(lang) or d.get("en") if isinstance(d, dict) else d  # noqa: E731
    return {"id": qid, "title": pick(q["title"]), "intro": pick(q["intro"]), "items": [
        {"id": it["id"], "type": it["type"], "text": pick(it["text"]), "optional": bool(it.get("optional")),
         "low": pick(it["low"]) if it.get("low") else None, "high": pick(it["high"]) if it.get("high") else None,
         "options": [{"value": o["value"], "label": pick(o), "exclusive": bool(o.get("exclusive"))} for o in it.get("options", [])]}
        for it in q["items"]]}


def label_of(qid: str, item_id: str, value: str, lang: str = "en") -> str:
    it = next((i for i in questionnaires()[qid]["items"] if i["id"] == item_id), None)
    o = next((o for o in (it or {}).get("options", []) if o["value"] == value), None)
    return (o.get(lang) or o["en"]) if o else value


def list_checkins(fhir: FhirStore, patient_id: str) -> list[dict]:
    qrs = [q for q in fhir.search("QuestionnaireResponse", patient=f"Patient/{patient_id}")
           if (q.get("questionnaire") or "").startswith(VC_Q + "/vc-daily")]
    return sorted(qrs, key=lambda q: q.get("authored", ""))


def parse(qr: dict) -> dict:
    vals: dict[str, object] = {}
    for it in qr.get("item", []):
        ans = it.get("answer", [])
        if not ans:
            continue
        if it["linkId"] in ("focus_lost", "triggers", "side_effects"):
            vals[it["linkId"]] = [a.get("valueString") for a in ans]
        elif "valueInteger" in ans[0]:
            vals[it["linkId"]] = ans[0]["valueInteger"]
        else:
            vals[it["linkId"]] = ans[0].get("valueString")
    return {"date": qr["authored"][:10], "ref": f"QuestionnaireResponse/{qr['id']}", "values": vals}


def list_ref(patient_id: str) -> str:
    return f"List/list-checkins-{patient_id}"


def sync_list(fhir: FhirStore, patient_id: str) -> dict:
    qrs = list_checkins(fhir, patient_id)
    return fhir.update({
        "resourceType": "List", "id": f"list-checkins-{patient_id}", "status": "current", "mode": "working",
        "title": "Daily check-ins (patient-reported)", "subject": {"reference": f"Patient/{patient_id}"},
        "date": iso_now(), "source": {"reference": f"Patient/{patient_id}"},
        "entry": [{"item": {"reference": f"QuestionnaireResponse/{q['id']}"}, "date": q["authored"]} for q in qrs],
    })


def validate(qid: str, answers: dict) -> list[dict]:
    """Returns FHIR QuestionnaireResponse items; raises on unknown or missing answers."""
    items = []
    for it in questionnaires()[qid]["items"]:
        v = answers.get(it["id"])
        if v in (None, "", []):
            if it.get("optional"):
                continue
            raise CheckinError(422, f"Missing answer: {it['id']}")
        allowed = {o["value"] for o in it.get("options", [])}
        if it["type"] == "scale":
            if not isinstance(v, int) or not 0 <= v <= 10:
                raise CheckinError(422, f"{it['id']} must be 0-10")
            items.append({"linkId": it["id"], "text": it["text"]["en"], "answer": [{"valueInteger": v}]})
        elif it["type"] == "multi":
            vs = v if isinstance(v, list) else [v]
            if any(x not in allowed for x in vs):
                raise CheckinError(422, f"Unknown option for {it['id']}")
            items.append({"linkId": it["id"], "text": it["text"]["en"], "answer": [{"valueString": x} for x in vs]})
        elif it["type"] == "single":
            if v not in allowed:
                raise CheckinError(422, f"Unknown option for {it['id']}")
            items.append({"linkId": it["id"], "text": it["text"]["en"], "answer": [{"valueString": v}]})
        else:
            items.append({"linkId": it["id"], "text": it["text"]["en"], "answer": [{"valueString": str(v)[:1000]}]})
    return items


def build_qr(patient_id: str, plan: dict, items: list[dict], authored: str, rid: str | None = None) -> dict:
    qid = plan_questionnaire(plan)
    r = {"resourceType": "QuestionnaireResponse", "status": "completed", "questionnaire": f"{VC_Q}/{qid}",
         "basedOn": [{"reference": f"CarePlan/{plan['id']}"}], "subject": {"reference": f"Patient/{patient_id}"},
         "source": {"reference": f"Patient/{patient_id}"}, "authored": authored, "item": items}
    if rid:
        r["id"] = rid
    return r


def submit(db: Session, fhir: FhirStore, user: User, patient_id: str, answers: dict, lang: str) -> dict:
    plan = active_plan(fhir, patient_id)
    if not plan:
        raise CheckinError(404, "No daily check-in plan")
    qid = plan_questionnaire(plan)
    items = validate(qid, answers)

    # Safety net first: free text, plus the answers as the patient saw them.
    said = " ".join([str(answers.get("note") or "")] + [label_of(qid, k, x, lang) for k, v in answers.items()
                                                         if k != "note" for x in (v if isinstance(v, list) else [str(v)])])
    flag = safety.check_text(said)
    existing = next((q for q in list_checkins(fhir, patient_id) if q["authored"][:10] == today().isoformat()), None)
    qr = fhir.update(build_qr(patient_id, plan, items, iso_now(), rid=existing["id"])) if existing \
        else fhir.create(build_qr(patient_id, plan, items, iso_now()))
    sync_list(fhir, patient_id)
    audit.record(db, user.id, "patient", "checkin.submit", patient_id, f"QuestionnaireResponse/{qr['id']}")
    if flag:
        appt = next((a for a in fhir.search("Appointment", patient=f"Patient/{patient_id}") if a.get("status") == "booked"), None)
        db.add(UrgentFlag(patient_id=patient_id, session_id=f"checkin:{qr['id']}", appointment_id=(appt or {}).get("id", ""),
                          rule_id=flag.rule_id, trigger_text=f'{flag.label}. Daily check-in note: "{answers.get("note") or said}"',
                          created_at=now()))
        db.commit()
        audit.record(db, user.id, "patient", "checkin.emergency", patient_id, f"QuestionnaireResponse/{qr['id']}", reason=flag.rule_id)
    return {"ref": f"QuestionnaireResponse/{qr['id']}", "emergency": flag.rule_id if flag else None}
