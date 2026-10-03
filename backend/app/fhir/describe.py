"""Human-readable views of FHIR resources (source drawer, medication overview, profile).
Source (clinic vs patient-reported) is derived from the resource itself, never from LLM output."""
from __future__ import annotations

from datetime import date

from app.settings import today

VC = "https://vitalcontext.example"
EXT_OUTCOME = f"{VC}/fhir/StructureDefinition/visit-outcome"
EXT_PRESCRIBER = f"{VC}/fhir/StructureDefinition/reported-prescriber"
EXT_BRIEF = f"{VC}/fhir/StructureDefinition/brief-payload"
EXT_APPOINTMENT = f"{VC}/fhir/StructureDefinition/appointment"
LIFESTYLE_SYSTEM = f"{VC}/lifestyle"
WEARABLE_SYSTEM = f"{VC}/wearable"


def ext(resource: dict, url: str) -> str | None:
    return next((e.get("valueString") for e in resource.get("extension", []) if e.get("url") == url), None)


def fmt_date(d: str | None) -> str:
    if not d:
        return ""
    parts = d[:10].split("-")
    try:
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1).strftime("%b %Y")
        x = date.fromisoformat(d[:10])
        return f"{x.day} {x.strftime('%b %Y')}"
    except ValueError:
        return d


def months_since(d: str | None) -> int | None:
    if not d:
        return None
    parts = [int(x) for x in d[:10].split("-")] + [1, 1]
    y, m, dd = parts[0], parts[1], parts[2]
    t = today()
    return (t.year - y) * 12 + (t.month - m) - (1 if t.day < dd else 0)


def is_registry(r: dict) -> bool:
    return any(t.get("code") == "public-registry" for t in (r.get("meta") or {}).get("tag", []))


def source_of(r: dict) -> str:
    rt = r.get("resourceType")
    if is_registry(r):
        return "registry"
    if rt == "QuestionnaireResponse":
        return "patient"
    if rt == "List" and (r.get("source") or {}).get("reference", "").startswith("Patient/"):
        return "patient"
    if rt == "MedicationStatement" and (r.get("informationSource") or {}).get("reference", "").startswith("Patient/"):
        return "patient"
    if rt == "Observation" and any(p.get("reference", "").startswith("Patient/") for p in r.get("performer", [])):
        return "patient"
    return "clinic"


def codings(r: dict, key: str = "code") -> list[dict]:
    return (r.get(key) or {}).get("coding", [])


def lifestyle_key(r: dict) -> str | None:
    return next((c["code"] for c in codings(r) if c.get("system") == LIFESTYLE_SYSTEM), None)


def wearable_kind(r: dict) -> str | None:
    return next((c["code"] for c in codings(r) if c.get("system") == WEARABLE_SYSTEM), None)


def med_view(r: dict) -> dict:
    """Normalised medicine row for both MedicationRequest and MedicationStatement."""
    cc = r.get("medicationCodeableConcept") or {}
    name = cc.get("text") or next((c.get("display") for c in cc.get("coding", [])), "Medicine")
    atc = next((c.get("code") for c in cc.get("coding", []) if "atc" in c.get("system", "")), None)
    if r["resourceType"] == "MedicationRequest":
        dose = ((r.get("dosageInstruction") or [{}])[0]).get("text", "")
        period = (r.get("dispenseRequest") or {}).get("validityPeriod") or {}
        start, end = r.get("authoredOn"), period.get("end") if r.get("status") != "active" else None
        reason = (r.get("reasonCode") or [{}])[0].get("text") if r.get("reasonCode") else None
        return {"name": name, "atc": atc, "dose": dose, "frequency": "", "start": start, "end": end,
                "status": r.get("status"), "reason": reason, "reason_ref": ((r.get("reasonReference") or [{}])[0]).get("reference"),
                "prescriber": (r.get("requester") or {}).get("display"), "other_provider": False, "note": None}
    dosage = (r.get("dosage") or [{}])[0]
    period = r.get("effectivePeriod") or {}
    notes = [n.get("text") for n in r.get("note", [])]
    return {"name": name, "atc": atc, "dose": dosage.get("text", ""),
            "frequency": ((dosage.get("timing") or {}).get("code") or {}).get("text", ""),
            "start": period.get("start"), "end": period.get("end"), "status": r.get("status"),
            "reason": (r.get("reasonCode") or [{}])[0].get("text") if r.get("reasonCode") else None, "reason_ref": None,
            "prescriber": ext(r, EXT_PRESCRIBER), "other_provider": bool(ext(r, EXT_PRESCRIBER)),
            "note": notes[0] if notes else None, "asserted": r.get("dateAsserted")}


def title_of(r: dict) -> str:
    rt = r["resourceType"]
    if rt in ("MedicationRequest", "MedicationStatement"):
        m = med_view(r)
        return f"{m['name']} {m['dose']}".strip() if m["dose"] and m["dose"].split()[0][0].isdigit() and rt == "MedicationStatement" else m["name"]
    if rt == "Condition":
        return next((c.get("display") for c in codings(r)), (r.get("code") or {}).get("text", "Condition"))
    if rt == "Encounter":
        return "Visit: " + ((r.get("reasonCode") or [{}])[0].get("text", "visit"))
    if rt == "DocumentReference":
        return (r.get("type") or {}).get("text", "Document")
    if rt == "AllergyIntolerance":
        return f"Allergy: {(r.get('code') or {}).get('text', '')}"
    if rt == "Observation":
        return (r.get("code") or {}).get("text") or next((c.get("display") for c in codings(r) if c.get("display")), "Observation")
    if rt == "QuestionnaireResponse":
        return "Daily check-in" if "vc-daily" in (r.get("questionnaire") or "") else "Pre-visit intake chat"
    if rt in ("List", "CarePlan"):
        return r.get("title", rt)
    if rt == "Composition":
        return r.get("title", "Pre-visit brief")
    if rt == "Provenance":
        return "Medication reconciliation"
    return rt


def date_of(r: dict) -> str | None:
    rt = r["resourceType"]
    if rt == "MedicationRequest":
        return r.get("authoredOn")
    if rt == "MedicationStatement":
        return r.get("dateAsserted") or (r.get("effectivePeriod") or {}).get("start")
    if rt == "Condition":
        return r.get("recordedDate") or r.get("onsetDateTime")
    if rt == "Encounter":
        return (r.get("period") or {}).get("start")
    if rt == "DocumentReference":
        return r.get("date")
    if rt == "AllergyIntolerance":
        return r.get("recordedDate")
    if rt == "Observation":
        return r.get("effectiveDateTime") or (r.get("effectivePeriod") or {}).get("end")
    if rt == "QuestionnaireResponse":
        return r.get("authored")
    if rt in ("Composition", "List"):
        return r.get("date")
    if rt == "CarePlan":
        return (r.get("period") or {}).get("start")
    return (r.get("meta") or {}).get("lastUpdated")


def fields_of(r: dict) -> list[tuple[str, str]]:
    rt = r["resourceType"]
    f: list[tuple[str, str]] = []
    if rt in ("MedicationRequest", "MedicationStatement"):
        m = med_view(r)
        f.append(("Dose", " ".join(x for x in (m["dose"], m["frequency"]) if x) or "Not given"))
        f.append(("Status", m["status"] or ""))
        if m["start"]:
            f.append(("Started" if rt == "MedicationStatement" else "Prescribed", fmt_date(m["start"])))
        if m["end"]:
            f.append(("Ended", fmt_date(m["end"])))
        if rt == "MedicationRequest":
            if m["prescriber"]:
                f.append(("Prescriber", m["prescriber"]))
            if m["reason_ref"]:
                disp = ((r.get("reasonReference") or [{}])[0]).get("display")
                f.append(("Reason", f"{disp} ({m['reason_ref']})" if disp else m["reason_ref"]))
            elif m["reason"]:
                f.append(("Reason", m["reason"]))
        else:
            f.append(("Prescriber", m["prescriber"] or ("None, bought without prescription" if (m["note"] or "").lower().startswith("over the counter") else "Not given")))
            f.append(("Reason", m["reason"] or "Not given"))
            if m["note"]:
                f.append(("Note", m["note"]))
            f.append(("Reported by", "Patient, profile entry"))
        from app.services.knowledge import drug_facts
        facts = drug_facts(m["name"], m["atc"])
        if facts.get("listed_side_effects"):
            f.append(("Product info", "URPL registry lists " + ", ".join(facts["listed_side_effects"])
                      + f" among very common or common undesirable effects ({facts['registry_ref']})"))
    elif rt == "Condition":
        f += [("Code", " ".join(f"{c.get('code')}" for c in codings(r))), ("Clinical status", codings(r, "clinicalStatus")[0]["code"] if codings(r, "clinicalStatus") else ""),
              ("Onset", fmt_date(r.get("onsetDateTime"))), ("Recorded by", (r.get("recorder") or {}).get("display", ""))]
    elif rt == "Encounter":
        f += [("Date", fmt_date((r.get("period") or {}).get("start"))), ("Reason", (r.get("reasonCode") or [{}])[0].get("text", "")),
              ("Outcome", ext(r, EXT_OUTCOME) or "Not recorded")]
        who = next(((p.get("individual") or {}).get("display") for p in r.get("participant", []) if p.get("individual")), None)
        if who:
            f.append(("Clinician", who))
    elif rt == "DocumentReference" and is_registry(r):
        f += [("Source", ", ".join(a.get("display", "") for a in r.get("author", []))),
              ("Product", ((r.get("context") or {}).get("related") or [{}])[0].get("display", "")),
              ("Section 4.8", r.get("description", "")), ("Snapshot", fmt_date(r.get("date"))),
              ("Registry", ((r.get("content") or [{}])[0].get("attachment") or {}).get("url", ""))]
    elif rt == "DocumentReference":
        f += [("Date", fmt_date(r.get("date"))), ("Finding", r.get("description", "")),
              ("Author", ", ".join(a.get("display", "") for a in r.get("author", [])))]
    elif rt == "AllergyIntolerance":
        react = (r.get("reaction") or [{}])[0]
        f += [("Substance", (r.get("code") or {}).get("text", "")), ("Criticality", r.get("criticality", "")),
              ("Reaction", ", ".join(x.get("text", "") for x in react.get("manifestation", []))),
              ("Recorded", fmt_date(r.get("recordedDate")))]
    elif rt == "Observation":
        lk, wk = lifestyle_key(r), wearable_kind(r)
        if lk:
            f += [("Patient entry", r.get("valueString") or "No longer current"), ("Category", "social-history"),
                  ("Reported by", "Patient, profile entry")]
        elif wk:
            for c in r.get("component", []):
                q = c.get("valueQuantity") or {}
                f.append(((c.get("code") or {}).get("text", ""), f"{q.get('value', '')} {q.get('unit', '')}".strip()))
            f.append(("Source", "Patient-connected wearable (aggregates only)"))
        else:
            q = r.get("valueQuantity") or {}
            rr = (r.get("referenceRange") or [{}])[0]
            f.append(("Result", f"{q.get('value')} {q.get('unit', '')}".strip()))
            if rr:
                f.append(("Reference range", f"{(rr.get('low') or {}).get('value')}–{(rr.get('high') or {}).get('value')} {q.get('unit', '')}".strip()))
            interp = next((c.get("display") for c in (r.get("interpretation") or [{}])[0].get("coding", [])), None) if r.get("interpretation") else None
            if interp:
                f.append(("Interpretation", interp))
            f.append(("Date", fmt_date(r.get("effectiveDateTime"))))
    elif rt == "List":
        entries = r.get("entry", [])
        f += [("Entries", str(len(entries))),
              ("Period", f"{fmt_date(entries[0]['date'])} – {fmt_date(entries[-1]['date'])}" if entries else "none yet"),
              ("Reported by", "Patient, daily check-ins")]
        f += [(fmt_date(e["date"]), e["item"]["reference"]) for e in entries[-7:]]
    elif rt == "QuestionnaireResponse" and "vc-daily" in (r.get("questionnaire") or ""):
        f.append(("Date", fmt_date(r.get("authored"))))
        for it in r.get("item", []):
            ans = ", ".join(str(a.get("valueString", a.get("valueInteger", ""))) for a in it.get("answer", []))
            f.append((it.get("text", it["linkId"]), ans))
    elif rt == "QuestionnaireResponse":
        f += [("Completed", fmt_date(r.get("authored"))), ("Confirmed by patient", "Yes")]
        for it in r.get("item", []):
            if it.get("linkId") == "transcript":
                continue
            ans = ", ".join(a.get("valueString", "") for a in it.get("answer", []))
            f.append((it.get("text", it.get("linkId")), ans))
    return [(k, v) for k, v in f if v]
