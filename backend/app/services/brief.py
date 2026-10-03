"""Brief service. Triggered when an intake is submitted.

* T3 writes chief complaint, connections (with refs) and open questions.
* Citation validation: refs must exist in the reference map, otherwise the statement is dropped.
* Language filter: diagnostic / recommendation wording is dropped.
* Patient words are copied by code; the medication overview and lifestyle section are built by code
  from live FHIR data at read time, so profile edits show up immediately.
* Stored as a FHIR Composition (medical documentation).
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BriefReview, IntakeSession, User
from app.fhir.client import FhirStore, ref_of
from app.fhir.describe import EXT_APPOINTMENT, EXT_BRIEF, date_of, ext, fmt_date, med_view, months_since, source_of, title_of, wearable_kind
from app.llm.gateway import get_gateway
from app.llm.mock_provider import MockProvider
from app.llm.validation import has_diagnostic_wording
from app.services.context import build_context_pack, latest_lifestyle
from app.services.knowledge import relevance
from app.services.profile import LIFESTYLE, STALE_MONTHS
from app.settings import iso_now, today


def generate(db: Session, fhir: FhirStore, s: IntakeSession, qr_ref: str, gateway=None,
             composition_id: str | None = None, created: str | None = None) -> tuple[dict, list[str]]:
    ctx = build_context_pack(fhir, s.patient_id, s.category or "general")
    q1 = ctx.add_intake(qr_ref, s.answers)
    res = (gateway or get_gateway()).run("t3_brief", {"context_pack": ctx.pack}, db)
    out = res.output

    connections, dropped = [], 0
    for c in out.connections:
        refs = [r for r in c.refs]
        if not refs or any(r not in ctx.ref_map for r in refs) or has_diagnostic_wording(c.statement):
            dropped += 1
            continue
        connections.append({"statement": c.statement, "refs": [ctx.ref_map[r] for r in refs]})
    open_q = [q for q in out.open_questions if not has_diagnostic_wording(q)]
    dropped += len(out.open_questions) - len(open_q)
    cc = out.chief_complaint
    if has_diagnostic_wording(cc):
        cc = MockProvider._chief(s.category or "general", {a["slot"]: a["value"] for a in s.answers})
        dropped += 1

    payload = {
        "category": s.category,
        "chief_complaint": {"text": cc, "refs": [ctx.ref_map[q1]]},
        "patient_words": [a["value"] for a in s.answers if a.get("verbatim") or a["slot"] == "complaint"],
        "answers": [{"label": a["label"], "answer": a["value"]} for a in s.answers if a["slot"] != "complaint"],
        "correction": s.correction,
        "connections": connections,
        "open_questions": open_q,
        "generation": {"provider": res.provider, "prompt_version": res.prompt_version, "dropped_statements": dropped,
                       "context_records": len(ctx.ref_map) - 1, "total_records": ctx.total_records,
                       "degraded": res.degraded or bool(s.flags.get("degraded")),
                       "instruction_like_input": bool(s.flags.get("instruction_like_input"))},
    }
    sections = [
        {"title": "Chief complaint", "text": {"status": "generated", "div": f"<div>{_esc(cc)}</div>"},
         "entry": [{"reference": ctx.ref_map[q1]}]},
        {"title": "Relevant history", "entry": [{"reference": r} for c in connections for r in c["refs"]],
         "text": {"status": "generated", "div": "<div>" + "".join(f"<p>{_esc(c['statement'])}</p>" for c in connections) + "</div>"}},
        {"title": "Open questions", "text": {"status": "generated", "div": "<div>" + "".join(f"<p>{_esc(q)}</p>" for q in open_q) + "</div>"}},
    ]
    comp = fhir.create({
        "resourceType": "Composition", **({"id": composition_id} if composition_id else {}), "status": "final", "title": "Pre-visit brief",
        "type": {"coding": [{"system": "http://loinc.org", "code": "34133-9", "display": "Summary of episode note"}]},
        "subject": {"reference": f"Patient/{s.patient_id}"}, "date": created or iso_now(),
        "author": [{"display": "VitalContext (organises information only; no diagnoses)"}],
        "section": sections,
        "extension": [{"url": EXT_BRIEF, "valueString": json.dumps(payload, ensure_ascii=False)},
                      {"url": EXT_APPOINTMENT, "valueString": f"Appointment/{s.appointment_id}"}],
    })
    return comp, ctx.profile_refs


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def citation(fhir: FhirStore, ref: str) -> dict | None:
    rt, rid = ref.split("/", 1)
    r = fhir.read(rt, rid)
    if not r:
        return None
    return {"reference": ref, "source": source_of(r), "label": rid}


def _fact(fhir: FhirStore, text: str, refs: list[str], date: str | None = None) -> dict | None:
    cites = [citation(fhir, r) for r in refs]
    if not cites or any(c is None for c in cites):  # citation no longer resolves -> hide the fact
        return None
    if date is None:
        dated = [r for r in refs if not r.startswith("QuestionnaireResponse/")]
        if len(dated) == 1:
            date = (date_of(fhir.read(*dated[0].split("/", 1))) or "")[:10] or None
    return {"text": text, "date": date, "citations": cites, "sources": sorted({c["source"] for c in cites})}


def medication_overview(fhir: FhirStore, patient_id: str) -> list[dict]:
    pref = f"Patient/{patient_id}"
    provenance = [p for p in fhir.search("Provenance") if p.get("activity", {}).get("text") == "reconciled"]
    rows = []
    for rt in ("MedicationRequest", "MedicationStatement"):
        for r in fhir.search(rt, patient=pref):
            m = med_view(r)
            if m["status"] in ("entered-in-error", "cancelled"):
                continue
            current = m["status"] in ("active", "intended", "on-hold")
            end_or_date = m["end"] or date_of(r)
            if not current and (months_since(end_or_date) or 0) > 12:
                continue
            src = source_of(r)
            dose = " ".join(x for x in (m["dose"], m["frequency"]) if x)
            if current:
                dates = f"since {fmt_date(m['start'])}" if m["start"] else f"reported {fmt_date(date_of(r))}"
            else:
                dates = f"{fmt_date(m['start'])} – {fmt_date(m['end'])}" if m["start"] and m["end"] else (
                    f"stopped {fmt_date(m['end'])}" if m["end"] else fmt_date(date_of(r)))
            notes = []
            if src == "patient" and m["prescriber"]:
                notes.append(f"prescribed by {m['prescriber']}")
            elif src == "patient" and (m["note"] or "").lower().startswith("over the counter"):
                notes.append("over the counter")
            if src == "patient" and not current:
                notes.append("marked as no longer taken by the patient")
            rec = next((p for p in provenance if any(t.get("reference") == ref_of(r) for t in p.get("target", []))), None)
            rows.append({"reference": ref_of(r), "name": m["name"].split(" (")[0] if src == "patient" else title_of(r),
                         "dose": dose or "Not given", "dates": dates, "note": "; ".join(notes) or None,
                         "status": "current" if current else "past", "source": src,
                         "reconciled": {"by": rec["agent"][0]["who"]["display"], "at": rec["recorded"][:10]} if rec else None})
    rows.sort(key=lambda x: (x["status"] != "current", x["source"] != "clinic", x["name"].lower()))
    return rows


def lifestyle_section(fhir: FhirStore, patient_id: str, category: str) -> tuple[list[dict], list[str]]:
    cfg = relevance()["categories"].get(category, relevance()["categories"]["general"])
    obs = fhir.search("Observation", patient=f"Patient/{patient_id}")
    life = latest_lifestyle(obs)
    facts, gaps = [], []
    for key in cfg.get("lifestyle", []):
        r = life.get(key)
        label = LIFESTYLE[key]["label"]
        if not r or not r.get("valueString"):
            gaps.append(f"{label} not provided by the patient.")
            continue
        d = (date_of(r) or "")[:10]
        m = months_since(d) or 0
        f = _fact(fhir, f"{label}: {r['valueString'].rstrip('.')}.", [ref_of(r)], d)
        if f:
            f.update({"updatedAt": d, "monthsAgo": m, "stale": m >= STALE_MONTHS})
            facts.append(f)
            if m >= STALE_MONTHS:
                gaps.append(f"{label} record last updated {m} months ago.")
    if cfg.get("wearable"):
        for r in obs:
            if wearable_kind(r) == "weekly-summary":
                parts = [f"{(c.get('code') or {}).get('text', '').split(' (')[0].lower()} {(c.get('valueQuantity') or {}).get('value')} "
                         f"{(c.get('valueQuantity') or {}).get('unit', '')}".strip() for c in r.get("component", [])]
                d = (date_of(r) or "")[:10]
                f = _fact(fhir, "Wearable: " + ", ".join(parts) + ".", [ref_of(r)], d)
                if f:
                    m = months_since(d) or 0
                    f.update({"updatedAt": d, "monthsAgo": m, "stale": m >= STALE_MONTHS})
                    facts.append(f)
            elif wearable_kind(r) == "running-weekly":
                comps = r.get("component", [])
                if comps:
                    first, last = comps[0]["valueQuantity"]["value"], comps[-1]["valueQuantity"]["value"]
                    d = (date_of(r) or "")[:10]
                    f = _fact(fhir, f"Running about {last:g} km a week (wearable), up from {first:g} km in the week of {comps[0]['code']['text']}.",
                              [ref_of(r)], d)
                    if f:
                        f.update({"updatedAt": d, "monthsAgo": months_since(d) or 0, "stale": False})
                        facts.append(f)
    return facts, gaps


def find_session_for_brief(db: Session, brief_id: str) -> IntakeSession | None:
    return db.scalars(select(IntakeSession).where(IntakeSession.brief_id == brief_id)).first()


def read_brief(db: Session, fhir: FhirStore, patient_id: str, brief_id: str) -> dict | None:
    comp = fhir.read("Composition", brief_id)
    if not comp or comp.get("subject", {}).get("reference") != f"Patient/{patient_id}":
        return None
    p = json.loads(ext(comp, EXT_BRIEF) or "{}")
    category = p.get("category") or "general"
    cc = p["chief_complaint"]
    history = [f for c in p.get("connections", []) if (f := _fact(fhir, c["statement"], c["refs"]))]
    life, gaps = lifestyle_section(fhir, patient_id, category)
    meds = medication_overview(fhir, patient_id)
    open_q = list(p.get("open_questions", []))
    # Live, code-computed gaps (stale or missing profile data). Shown to the doctor only.
    open_q += [g for g in gaps if g not in open_q]
    for m in meds:
        if m["source"] == "patient" and m["status"] == "current" and m["note"] and "prescribed by" in m["note"]:
            stmt = fhir.read(*m["reference"].split("/", 1))
            if stmt and not stmt.get("reasonCode"):
                q = f"{m['name']} (patient-reported, another provider): indication not given."
                if q not in open_q:
                    open_q.insert(0, q)
    review = db.scalars(select(BriefReview).where(BriefReview.brief_id == brief_id).order_by(BriefReview.at.desc())).first()
    reviewer = db.get(User, review.doctor_id) if review else None
    return {
        "id": brief_id,
        "patientId": patient_id,
        "createdAt": comp.get("date"),
        "category": category,
        "chiefComplaint": _fact(fhir, cc["text"], cc["refs"]) or {"text": cc["text"], "citations": [], "sources": []},
        "patientWords": p.get("patient_words", []),
        "intakeAnswers": p.get("answers", []),
        "patientCorrection": p.get("correction"),
        "medications": meds,
        "relevantHistory": history,
        "lifestyle": life,
        "openQuestions": open_q,
        "reviewed": {"by": reviewer.display_name, "at": review.at.isoformat()} if review else None,
        "generation": {**p.get("generation", {}), "hidden_unresolved": len(p.get("connections", [])) - len(history)},
    }


def brief_as_text(b: dict, patient_name: str) -> str:
    lines = [f"Pre-visit brief: {patient_name}", f"Chief complaint: {b['chiefComplaint']['text']}"]
    if b["patientWords"]:
        lines.append("Patient's words: " + " / ".join(f'"{w}"' for w in b["patientWords"]))
    lines.append("Intake answers:")
    lines += [f"- {a['label']}: {a['answer']}" for a in b["intakeAnswers"]]
    if b.get("patientCorrection"):
        lines.append(f"Patient correction: {b['patientCorrection']}")
    lines.append("Medication overview (reconcile with the patient):")
    lines += [f"- [{m['status']}] {m['name']}, {m['dose']}, {m['dates']} ({'clinic' if m['source'] == 'clinic' else 'patient-reported'}; {m['reference']})"
              for m in b["medications"]]
    lines.append("Relevant history:")
    lines += [f"- {f['text']} [{', '.join(c['reference'] for c in f['citations'])}]" for f in b["relevantHistory"]]
    lines.append("Relevant lifestyle:")
    lines += [f"- {f['text']} (updated {f['updatedAt']})" for f in b["lifestyle"]]
    lines.append("Open questions:")
    lines += [f"- {q}" for q in b["openQuestions"]]
    lines.append(f"Generated {today().isoformat()} by VitalContext: organises information only, no diagnoses, risk scores or suggested actions.")
    return "\n".join(lines)
