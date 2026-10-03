"""Patient profile: lifestyle (Observation, social-history) and medicines from other providers
(MedicationStatement, informationSource = Patient).

Deletion rule: an entry not yet used in a confirmed intake can be deleted. Once it is part of
medical documentation it is read-only and can only be marked as no longer current (DELETE -> 409).
"""
from __future__ import annotations

from app.fhir.client import DOCUMENTED_TAG, FhirStore, is_documented, ref_of
from app.fhir.describe import (EXT_PRESCRIBER, LIFESTYLE_SYSTEM, WEARABLE_SYSTEM, date_of, lifestyle_key, med_view,
                               months_since, wearable_kind)
from app.services.context import latest_lifestyle
from app.settings import today

LIFESTYLE = {
    "smoking": {"label": "Smoking", "label_pl": "Palenie", "loinc": ("72166-2", "Tobacco smoking status"),
                "hint": "e.g. never smoked, or quit in 2019"},
    "alcohol": {"label": "Alcohol", "label_pl": "Alkohol", "loinc": ("11331-6", "History of alcohol use"),
                "hint": "How often, and roughly how much"},
    "activity": {"label": "Physical activity", "label_pl": "Aktywność fizyczna", "loinc": ("73985-4", "Exercise activity"),
                 "hint": "Type, how often, how hard"},
    "sleep": {"label": "Sleep", "label_pl": "Sen", "loinc": ("93832-4", "Sleep duration"), "hint": "How long, how regular"},
    "diet": {"label": "Diet", "label_pl": "Dieta", "loinc": ("81663-7", "Diet"), "hint": "Pattern or restrictions"},
    "occupation": {"label": "Work", "label_pl": "Praca", "loinc": ("11341-5", "History of occupation"),
                   "hint": "Sitting or physical, shifts, stress"},
    "substances": {"label": "Other substances", "label_pl": "Inne substancje", "loinc": None, "hint": "Optional",
                   "optional": True},
}
STALE_MONTHS = 6


class ProfileError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def lifestyle_observation(patient_id: str, key: str, value: str, when: str, rid: str | None = None) -> dict:
    cfg = LIFESTYLE[key]
    coding = [{"system": LIFESTYLE_SYSTEM, "code": key, "display": cfg["label"]}]
    if cfg["loinc"]:
        coding.append({"system": "http://loinc.org", "code": cfg["loinc"][0], "display": cfg["loinc"][1]})
    r = {"resourceType": "Observation", "status": "final",
         "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "social-history"}]}],
         "code": {"coding": coding, "text": cfg["label"]},
         "subject": {"reference": f"Patient/{patient_id}"}, "performer": [{"reference": f"Patient/{patient_id}"}],
         "effectiveDateTime": when}
    if value:
        r["valueString"] = value
    else:
        r["dataAbsentReason"] = {"text": "No longer current (marked by patient)"}
    if rid:
        r["id"] = rid
    return r


def medication_statement(patient_id: str, name: str, dose: str = "", frequency: str = "", start: str | None = None,
                         end: str | None = None, reason: str | None = None, prescriber: str | None = None,
                         note: str | None = None, asserted: str | None = None, status: str = "active",
                         rid: str | None = None) -> dict:
    r: dict = {"resourceType": "MedicationStatement", "status": status, "medicationCodeableConcept": {"text": name},
               "subject": {"reference": f"Patient/{patient_id}"},
               "informationSource": {"reference": f"Patient/{patient_id}"},
               "dateAsserted": asserted or today().isoformat(),
               "dosage": [{"text": dose, **({"timing": {"code": {"text": frequency}}} if frequency else {})}]}
    period = {k: v for k, v in (("start", start), ("end", end)) if v}
    if period:
        r["effectivePeriod"] = period
    if reason:
        r["reasonCode"] = [{"text": reason}]
    if prescriber:
        r["extension"] = [{"url": EXT_PRESCRIBER, "valueString": prescriber}]
    if note:
        r["note"] = [{"text": note}]
    if rid:
        r["id"] = rid
    return r


def mark_documented(fhir: FhirStore, refs: list[str]) -> None:
    for ref in refs:
        rt, rid = ref.split("/", 1)
        r = fhir.read(rt, rid)
        if r and not is_documented(r):
            r.setdefault("meta", {}).setdefault("tag", []).append(DOCUMENTED_TAG)
            fhir.update(r)


# ---- read ---------------------------------------------------------------------------------
def get_profile(fhir: FhirStore, patient_id: str) -> dict:
    pref = f"Patient/{patient_id}"
    obs = fhir.search("Observation", patient=pref)
    life = latest_lifestyle(obs)
    wear = [o for o in obs if wearable_kind(o) == "weekly-summary"]
    wear = max(wear, key=lambda o: date_of(o) or "") if wear else None
    items = []
    for key, cfg in LIFESTYLE.items():
        r = life.get(key)
        items.append({"key": key, "label": cfg["label"], "labelPl": cfg["label_pl"], "hint": cfg["hint"],
                      "optional": bool(cfg.get("optional")), "value": (r or {}).get("valueString", ""),
                      "updatedAt": (date_of(r) or "")[:10] if r else None, "documented": bool(r and is_documented(r)),
                      "reference": ref_of(r) if r else None})
    meds = []
    for r in fhir.search("MedicationStatement", patient=pref):
        if r.get("status") == "entered-in-error":
            continue
        m = med_view(r)
        meds.append({"id": r["id"], "name": m["name"], "dose": m["dose"], "frequency": m["frequency"], "start": m["start"],
                     "end": m["end"], "reason": m["reason"], "prescriber": m["prescriber"], "note": m["note"],
                     "status": m["status"], "current": m["status"] == "active", "updatedAt": (date_of(r) or "")[:10],
                     "documented": is_documented(r)})
    meds.sort(key=lambda m: (not m["current"], m["name"].lower()))
    wearable = None
    if wear:
        comps = {(c.get("code") or {}).get("text"): (c.get("valueQuantity") or {}) for c in wear.get("component", [])}
        wearable = {"updatedAt": (date_of(wear) or "")[:10],
                    "metrics": [{"label": k, "value": v.get("value"), "unit": v.get("unit", "")} for k, v in comps.items()]}
    return {"lifestyle": items, "medications": meds, "wearable": wearable}


def stale(d: str | None) -> bool:
    m = months_since(d)
    return m is not None and m >= STALE_MONTHS


# ---- write --------------------------------------------------------------------------------
def put_lifestyle(fhir: FhirStore, patient_id: str, key: str, value: str) -> dict:
    if key not in LIFESTYLE:
        raise ProfileError(404, "unknown_item", "Unknown profile item")
    value = value.strip()
    if not value:
        return delete_lifestyle(fhir, patient_id, key)
    cur = latest_lifestyle(fhir.search("Observation", patient=f"Patient/{patient_id}")).get(key)
    when = today().isoformat()
    if cur and not is_documented(cur):
        return fhir.update(lifestyle_observation(patient_id, key, value, when, rid=cur["id"]))
    # documented (or missing): a new Observation; the documented one stays untouched
    return fhir.create(lifestyle_observation(patient_id, key, value, when))


def delete_lifestyle(fhir: FhirStore, patient_id: str, key: str, mark_not_current: bool = False) -> dict:
    obs = [o for o in fhir.search("Observation", patient=f"Patient/{patient_id}") if lifestyle_key(o) == key]
    cur = latest_lifestyle(obs).get(key)
    if not cur or not cur.get("valueString"):
        return {"deleted": False}
    older_documented = any(is_documented(o) for o in obs if o["id"] != cur["id"])
    if is_documented(cur) and not mark_not_current:
        raise ProfileError(409, "documented", "This entry is part of your medical record. You can mark it as no longer current.")
    if is_documented(cur) or older_documented:
        fhir.create(lifestyle_observation(patient_id, key, "", today().isoformat()))
        return {"deleted": False, "markedNotCurrent": True}
    fhir.delete("Observation", cur["id"])
    return {"deleted": True}


def _own_statement(fhir: FhirStore, patient_id: str, mid: str) -> dict:
    r = fhir.read("MedicationStatement", mid)
    if not r or r.get("subject", {}).get("reference") != f"Patient/{patient_id}" \
            or r.get("informationSource", {}).get("reference") != f"Patient/{patient_id}":
        raise ProfileError(404, "not_found", "Medicine not found")
    return r


def add_medication(fhir: FhirStore, patient_id: str, data: dict) -> dict:
    return fhir.create(medication_statement(patient_id, **data))


def patch_medication(fhir: FhirStore, patient_id: str, mid: str, data: dict) -> dict:
    r = _own_statement(fhir, patient_id, mid)
    if data.get("current") is False:
        r["status"] = "stopped"
        r.setdefault("effectivePeriod", {})["end"] = data.get("end") or today().isoformat()
        r["dateAsserted"] = today().isoformat()
        return fhir.update(r)
    if is_documented(r):
        raise ProfileError(409, "documented", "This medicine is part of your medical record. You can mark it as no longer taken.")
    m = med_view(r)
    merged = {"name": m["name"], "dose": m["dose"], "frequency": m["frequency"], "start": m["start"], "end": m["end"],
              "reason": m["reason"], "prescriber": m["prescriber"], "note": m["note"]}
    merged.update({k: v for k, v in data.items() if k in merged and v is not None})
    return fhir.update(medication_statement(patient_id, **merged, rid=mid, status=r["status"]))


def delete_medication(fhir: FhirStore, patient_id: str, mid: str) -> None:
    r = _own_statement(fhir, patient_id, mid)
    if is_documented(r):
        raise ProfileError(409, "documented", "This medicine is part of your medical record. You can mark it as no longer taken.")
    fhir.delete("MedicationStatement", mid)


def put_wearable(fhir: FhirStore, patient_id: str, steps_per_day: int | None, resting_hr: int | None,
                 sleep_hours: float | None) -> dict:
    """Aggregate fields only. No location, no raw time series."""
    comps = []
    if steps_per_day is not None:
        comps.append({"code": {"text": "Steps per day (7-day average)"}, "valueQuantity": {"value": steps_per_day, "unit": "steps"}})
    if resting_hr is not None:
        comps.append({"code": {"text": "Resting heart rate"}, "valueQuantity": {"value": resting_hr, "unit": "bpm"}})
    if sleep_hours is not None:
        comps.append({"code": {"text": "Sleep (average)"}, "valueQuantity": {"value": sleep_hours, "unit": "h"}})
    r = {"resourceType": "Observation", "status": "final",
         "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "activity"}]}],
         "code": {"coding": [{"system": WEARABLE_SYSTEM, "code": "weekly-summary"}], "text": "Wearable weekly summary"},
         "subject": {"reference": f"Patient/{patient_id}"}, "performer": [{"reference": f"Patient/{patient_id}"}],
         "effectiveDateTime": today().isoformat(), "component": comps}
    return fhir.create(r)


def wipe(fhir: FhirStore, patient_id: str) -> dict:
    deleted = marked = 0
    for key in LIFESTYLE:
        res = delete_lifestyle(fhir, patient_id, key, mark_not_current=True)
        deleted += bool(res.get("deleted"))
        marked += bool(res.get("markedNotCurrent"))
    for r in fhir.search("MedicationStatement", patient=f"Patient/{patient_id}"):
        if r.get("informationSource", {}).get("reference") != f"Patient/{patient_id}" or r.get("status") != "active":
            continue
        if is_documented(r):
            patch_medication(fhir, patient_id, r["id"], {"current": False})
            marked += 1
        else:
            fhir.delete("MedicationStatement", r["id"])
            deleted += 1
    return {"deleted": deleted, "markedNotCurrent": marked}
