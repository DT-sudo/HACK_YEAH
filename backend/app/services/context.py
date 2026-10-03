"""Context engine: builds the context pack, the ONLY patient data an LLM ever sees.

1. Deterministic retrieval from FHIR by patient id (from the auth token / care assignment).
2. Relevance filter by complaint category (config/relevance.yaml).
3. Pseudonymisation: no names, PESEL, addresses, contact data or record ids. Birth date -> age.
   Every resource gets a per-request reference (R1, R2, ...); the map back to FHIR ids stays here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.fhir.client import FhirStore, ref_of
from app.fhir.describe import (EXT_OUTCOME, codings, date_of, ext, lifestyle_key, med_view, months_since, source_of,
                               title_of, wearable_kind)
from app.llm.framework import norm
from app.services.knowledge import drug_facts, relevance
from app.settings import today


@dataclass
class ContextPack:
    pack: dict
    ref_map: dict[str, str]  # R1 -> "MedicationRequest/mr-4471" (server-side only)
    total_records: int
    profile_refs: list[str] = field(default_factory=list)  # patient-profile resources included

    def add_intake(self, qr_ref: str, answers: list[dict]) -> str:
        ref = "Q1"
        self.ref_map[ref] = qr_ref
        self.pack["records"].append({"ref": ref, "kind": "intake", "source": "patient", "date": today().isoformat(),
                                     "title": "Confirmed pre-visit intake",
                                     "details": {"answers": [{"slot": a["slot"], "label": a["label"], "value": a["value"]} for a in answers]}})
        return ref


CLINICAL_TYPES = ["MedicationRequest", "MedicationStatement", "Condition", "Encounter", "DocumentReference",
                  "AllergyIntolerance", "Observation"]


def age_of(birth: str | None) -> int | None:
    if not birth:
        return None
    b = date.fromisoformat(birth)
    t = today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def _within(d: str | None, months: int) -> bool:
    m = months_since(d)
    return m is not None and m <= months


def latest_lifestyle(resources: list[dict]) -> dict[str, dict]:
    def order(r: dict) -> tuple[str, str]:
        return ((date_of(r) or "")[:10], (r.get("meta") or {}).get("lastUpdated", ""))

    out: dict[str, dict] = {}
    for r in resources:
        k = lifestyle_key(r)
        if k and (k not in out or order(r) >= order(out[k])):
            out[k] = r
    return out


def build_context_pack(fhir: FhirStore, patient_id: str, category: str) -> ContextPack:
    pref = f"Patient/{patient_id}"
    patient = fhir.read("Patient", patient_id) or {}
    cfg = relevance()["categories"].get(category, relevance()["categories"]["general"])
    hist_window = relevance()["history_window_months"]
    med_window = relevance()["medication_window_months"]

    all_res: list[dict] = []
    for rt in CLINICAL_TYPES:
        all_res += fhir.search(rt, patient=pref)

    selected: list[tuple[str, dict]] = []
    med_refs: dict[str, dict] = {}
    lab_watch: set[str] = set()

    def kw(text: str, words: list[str]) -> bool:
        n = norm(text)
        return any(norm(w) in n for w in words)

    for r in all_res:
        rt = r["resourceType"]
        if rt in ("MedicationRequest", "MedicationStatement"):
            m = med_view(r)
            if m["status"] in ("entered-in-error", "cancelled"):
                continue
            current = m["status"] in ("active", "intended", "on-hold")
            if current or _within(m["end"] or date_of(r), med_window):
                kind = "clinic_prescription" if rt == "MedicationRequest" else "reported_medication"
                selected.append((kind, r))
                med_refs[ref_of(r)] = r
                lab_watch.update(drug_facts(m["name"], m["atc"]).get("lab_watch", []))

    reason_refs = {med_view(r)["reason_ref"] for r in med_refs.values() if med_view(r)["reason_ref"]}
    loinc_watch = set(cfg.get("lab_loinc", [])) | ({"2160-0"} if "creatinine" in lab_watch else set())

    labs_latest: dict[str, dict] = {}
    for r in all_res:
        rt = r["resourceType"]
        if rt == "Condition":
            active = any(c.get("code") == "active" for c in codings(r, "clinicalStatus"))
            if ref_of(r) in reason_refs or (active and kw(title_of(r), cfg.get("encounter_keywords", []))):
                selected.append(("condition", r))
        elif rt == "Encounter":
            reason = " ".join(x.get("text", "") for x in r.get("reasonCode", []))
            if _within(date_of(r), hist_window) and kw(reason, cfg.get("encounter_keywords", [])):
                selected.append(("encounter", r))
        elif rt == "DocumentReference":
            if _within(r.get("date"), hist_window) and kw(title_of(r), cfg.get("document_keywords", [])):
                selected.append(("document", r))
        elif rt == "AllergyIntolerance":
            if any(c.get("code") == "active" for c in codings(r, "clinicalStatus")):
                selected.append(("allergy", r))
        elif rt == "Observation":
            loinc = next((c.get("code") for c in codings(r) if "loinc" in c.get("system", "")), None)
            cat_codes = {c.get("code") for cat in r.get("category", []) for c in cat.get("coding", [])}
            if "laboratory" in cat_codes and loinc in loinc_watch:
                if loinc not in labs_latest or (date_of(r) or "") > (date_of(labs_latest[loinc]) or ""):
                    labs_latest[loinc] = r
            elif wearable_kind(r) and cfg.get("wearable"):
                selected.append(("wearable", r))
    selected += [("lab", r) for r in labs_latest.values()]

    if cfg.get("vitals"):  # latest vital signs (e.g. baseline before a stimulant)
        vit: dict[str, dict] = {}
        for r in all_res:
            cat_codes = {c.get("code") for cat in r.get("category", []) for c in cat.get("coding", [])}
            if r["resourceType"] == "Observation" and "vital-signs" in cat_codes:
                k = title_of(r)
                if k not in vit or (date_of(r) or "") > (date_of(vit[k]) or ""):
                    vit[k] = r
        selected += [("vital", r) for r in vit.values()]

    # Public registry product information for the medicines in the pack (shared reference data).
    for ref in {drug_facts(med_view(r)["name"], med_view(r)["atc"]).get("registry_ref") for r in med_refs.values()} - {None}:
        doc = fhir.read(*ref.split("/", 1))
        if doc:
            selected.append(("registry_entry", doc))

    life = latest_lifestyle([r for r in all_res if r["resourceType"] == "Observation"])
    for key in cfg.get("lifestyle", []):
        r = life.get(key)
        if r and r.get("valueString"):
            selected.append(("lifestyle", r))

    checkin_summary = None
    if cfg.get("checkins"):
        from app.services import trends
        t = trends.build(fhir, patient_id)
        if t and t["summary"]["after"]["days"]:
            lst = fhir.read("List", f"list-checkins-{patient_id}")
            if lst:
                selected.append(("checkins", lst))
                checkin_summary = t

    # ---- pseudonymise ----------------------------------------------------------------------
    records, ref_map, profile_refs = [], {}, []
    fhir_to_r: dict[str, str] = {}
    for i, (kind, r) in enumerate(selected, start=1):
        fhir_to_r[ref_of(r)] = f"R{i}"
    for kind, r in selected:
        rid = fhir_to_r[ref_of(r)]
        ref_map[rid] = ref_of(r)
        src = source_of(r)
        if src == "patient" and r["resourceType"] in ("MedicationStatement", "Observation"):
            profile_refs.append(ref_of(r))
        details = _checkins_details(checkin_summary) if kind == "checkins" else _details(kind, r, fhir_to_r)
        records.append({"ref": rid, "kind": kind, "source": src, "date": (date_of(r) or "")[:10],
                        "title": title_of(r) if kind != "checkins" else "Daily check-ins (summary)", "details": details})

    sex = patient.get("gender")
    pack = {
        "patient": {"age": age_of(patient.get("birthDate")), "sex": sex},
        "complaint_category": category,
        "today": today().isoformat(),
        "records": records,
    }
    return ContextPack(pack, ref_map, total_records=len(all_res), profile_refs=profile_refs)


def _checkins_details(t: dict) -> dict:
    """Aggregates only: the model never sees the individual daily entries or free-text notes."""
    s = t["summary"]
    return {"since": t["since"], "split_date": s["split"], "split_label": s["splitLabel"],
            "before": s["before"], "after": s["after"], "medicine": dict(s["med"]),
            "appetite_reduced_days": s["appetiteReduced"], "side_effect_days": dict(s["side"]),
            "trigger_days": dict(s["triggers"]), "focus_lost_days": dict(s["focusLost"])}


def _details(kind: str, r: dict, fhir_to_r: dict[str, str]) -> dict:
    if kind in ("clinic_prescription", "reported_medication"):
        m = med_view(r)
        facts = drug_facts(m["name"], m["atc"])
        d = {"name": m["name"].split(" (")[0], "dose": " ".join(x for x in (m["dose"], m["frequency"]) if x),
             "status": m["status"], "start": m["start"], "end": m["end"],
             "reason": m["reason"] or ("see " + fhir_to_r[m["reason_ref"]] if m["reason_ref"] in fhir_to_r else "not given"),
             "from_other_provider": m["other_provider"],
             "drug_class": facts.get("class"), "product_info_side_effects": facts.get("listed_side_effects", []),
             "used_for": facts.get("used_for", []), "lab_watch": facts.get("lab_watch", [])}
        if m["reason_ref"] in fhir_to_r:
            d["reason_ref"] = fhir_to_r[m["reason_ref"]]
        if facts.get("registry_ref") in fhir_to_r:
            d["registry_ref"] = fhir_to_r[facts["registry_ref"]]
            d["registry_effects"] = [{"term": e["term"], "freq": e["freq"], "aliases": e.get("aliases", [])}
                                     for e in facts.get("effects", [])]
        return d
    if kind == "registry_entry":
        return {"source": "public registry (URPL, simulated snapshot)", "text": r.get("description", "")}
    if kind == "vital":
        comps = [str((c.get("valueQuantity") or {}).get("value")) for c in r.get("component", [])]
        q = r.get("valueQuantity") or {}
        return {"name": title_of(r), "value": "/".join(comps) if comps else str(q.get("value")),
                "unit": "mmHg" if comps else q.get("unit", "")}
    if kind == "condition":
        return {"name": title_of(r), "status": next((c.get("code") for c in codings(r, "clinicalStatus")), None),
                "onset": r.get("onsetDateTime")}
    if kind == "encounter":
        return {"reason": (r.get("reasonCode") or [{}])[0].get("text", ""), "outcome": ext(r, EXT_OUTCOME)}
    if kind == "document":
        return {"type": title_of(r), "finding": r.get("description", "")}
    if kind == "allergy":
        react = (r.get("reaction") or [{}])[0]
        return {"substance": (r.get("code") or {}).get("text", ""), "criticality": r.get("criticality"),
                "reaction": ", ".join(x.get("text", "") for x in react.get("manifestation", []))}
    if kind == "lab":
        q = r.get("valueQuantity") or {}
        rr = (r.get("referenceRange") or [{}])[0]
        lo, hi = (rr.get("low") or {}).get("value"), (rr.get("high") or {}).get("value")
        v = q.get("value")
        return {"name": title_of(r), "loinc": next((c.get("code") for c in codings(r)), None), "value": v,
                "unit": q.get("unit", ""), "range_low": lo, "range_high": hi,
                "abnormal": v is not None and ((lo is not None and v < lo) or (hi is not None and v > hi)),
                "months_ago": months_since(r.get("effectiveDateTime"))}
    if kind == "lifestyle":
        return {"topic": lifestyle_key(r), "value": r.get("valueString", ""), "updated": date_of(r),
                "months_since_update": months_since(date_of(r))}
    if kind == "wearable":
        comps = [{"label": (c.get("code") or {}).get("text", ""), "value": (c.get("valueQuantity") or {}).get("value"),
                  "unit": (c.get("valueQuantity") or {}).get("unit", "")} for c in r.get("component", [])]
        if wearable_kind(r) == "running-weekly":
            return {"metric": "running distance", "unit": comps[0]["unit"] if comps else "km",
                    "series": [{"period": c["label"], "value": c["value"]} for c in comps]}
        if wearable_kind(r) in ("rhr-daily", "sleep-daily"):  # daily aggregates: send a summary, not the series
            vals = [c["value"] for c in comps if c["value"] is not None]
            return {"metric": title_of(r), "unit": comps[0]["unit"] if comps else "", "days": len(vals),
                    "first_day": comps[0]["label"] if comps else None, "last_day": comps[-1]["label"] if comps else None,
                    "mean": round(sum(vals) / len(vals), 1) if vals else None}
        return {"summary": comps}
    return {}
