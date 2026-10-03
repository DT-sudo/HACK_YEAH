"""'Since last visit' trends and the consistency check. Deterministic code only, no AI.

* Daily series from check-ins (patient-reported) and wearable aggregates (patient device).
* Medication events (dose changes) from the clinic's MedicationRequests.
* Trend facts: descriptive averages and counts, each citing its sources. No interpretation.
* Consistency check: where sources disagree (what the patient said in the chat vs. check-ins vs.
  device data vs. clinic records). Shown to the doctor as conversation prompts, never as a verdict.
"""
from __future__ import annotations

from collections import Counter
from statistics import mean

from app.fhir.client import FhirStore, ref_of
from app.fhir.describe import fmt_date, med_view, wearable_kind
from app.services import checkins

TRIGGER = {"phone": "phone or notifications", "noise": "noise or open office", "meetings": "long meetings",
           "poor_sleep": "tiredness after poor sleep", "hunger": "hunger"}
WHEN = {"morning": "morning", "early_afternoon": "early afternoon", "late_afternoon": "late afternoon", "evening": "evening"}
SIDE = {"insomnia": "trouble falling asleep", "racing_heart": "racing heart", "headache": "headache",
        "irritability": "irritability", "dry_mouth": "dry mouth"}


def _avg(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(mean(xs), 1) if xs else None


def _daily_series(fhir: FhirStore, pid: str, kind: str) -> tuple[dict[str, float], str | None]:
    obs = [o for o in fhir.search("Observation", patient=f"Patient/{pid}") if wearable_kind(o) == kind]
    if not obs:
        return {}, None
    o = obs[0]
    return {c["code"]["text"]: c["valueQuantity"]["value"] for c in o.get("component", [])}, ref_of(o)


def build(fhir: FhirStore, pid: str) -> dict | None:
    plan = checkins.active_plan(fhir, pid)
    if not plan:
        return None
    since = (plan.get("period") or {}).get("start", "")[:10]
    days = [checkins.parse(q) for q in checkins.list_checkins(fhir, pid)]
    days = [d for d in days if d["date"] >= since]
    rhr, rhr_ref = _daily_series(fhir, pid, "rhr-daily")
    sleep_dev, sleep_ref = _daily_series(fhir, pid, "sleep-daily")

    # Medication events: clinic prescriptions for the condition the plan addresses.
    cond = ((plan.get("addresses") or [{}])[0]).get("reference")
    events = []
    for r in fhir.search("MedicationRequest", patient=f"Patient/{pid}"):
        if cond and ((r.get("reasonReference") or [{}])[0]).get("reference") != cond:
            continue
        m = med_view(r)
        if (m["start"] or "") >= since or r.get("status") == "active":
            events.append({"date": (m["start"] or "")[:10], "label": m["name"].removesuffix(" tablet"), "ref": ref_of(r),
                           "active": r.get("status") == "active"})
    events.sort(key=lambda e: e["date"])
    change = next((e for e in reversed(events) if since < e["date"]), None)

    all_dates = sorted({d["date"] for d in days} | {k for k in rhr if k >= since} | {k for k in sleep_dev if k >= since})
    by_date = {d["date"]: d for d in days}
    series = []
    for dt in all_dates:
        v = (by_date.get(dt) or {}).get("values", {})
        series.append({
            "date": dt, "ref": (by_date.get(dt) or {}).get("ref"),
            "focus": v.get("focus"), "sleepSelf": float(v["sleep"]) if v.get("sleep") else None,
            "sleepDevice": sleep_dev.get(dt), "restingHr": rhr.get(dt), "med": v.get("med_taken"),
            "appetite": v.get("appetite"), "sideEffects": [x for x in v.get("side_effects", []) if x != "none"],
            "triggers": [x for x in v.get("triggers", []) if x != "none"],
            "focusLost": [x for x in v.get("focus_lost", []) if x != "none"], "note": v.get("note"),
        })

    split = change["date"] if change else None
    before = [s for s in series if split and s["date"] < split]
    after = [s for s in series if not split or s["date"] >= split]
    checked_after = [s for s in after if s["ref"]]

    def stats(rows: list[dict]) -> dict:
        checked = [s for s in rows if s["ref"]]
        return {"days": len(checked), "focus": _avg([s["focus"] for s in checked]),
                "sleepSelf": _avg([s["sleepSelf"] for s in checked]),
                "sleepDevice": _avg([s["sleepDevice"] for s in rows]), "restingHr": _avg([s["restingHr"] for s in rows])}

    summary = {
        "split": split, "splitLabel": change["label"] if change else None, "splitRef": change["ref"] if change else None,
        "before": stats(before) if split else None, "after": stats(after),
        "med": Counter(s["med"] for s in checked_after if s["med"]),
        "appetiteReduced": sum(1 for s in checked_after if s["appetite"] in ("lower", "skipped")),
        "side": Counter(x for s in checked_after for x in s["sideEffects"]),
        "triggers": Counter(x for s in checked_after for x in s["triggers"]),
        "focusLost": Counter(x for s in checked_after for x in s["focusLost"]),
        "notes": [{"date": s["date"], "text": s["note"], "ref": s["ref"]} for s in series if s["note"]],
    }
    return {"since": since, "series": series, "events": events, "summary": summary,
            "refs": {"list": checkins.list_ref(pid), "rhr": rhr_ref, "sleep": sleep_ref},
            "plan": {"title": plan.get("title"), "ref": ref_of(plan)}}


def _pct(n: int, d: int) -> str:
    return f"{n} of {d} days"


def trend_facts(t: dict) -> list[dict]:
    """Descriptive trend statements (code-written). Each carries the references it rests on."""
    s, refs = t["summary"], t["refs"]
    a, b = s["after"], s["before"]
    lst = refs["list"]
    span = f"since {fmt_date(s['split'])}" if s["split"] else f"since {fmt_date(t['since'])}"
    first = f"since the change to {s['splitLabel']} on {fmt_date(s['split'])}" if s["split"] else span
    out = []
    if a["focus"] is not None:
        txt = f"Self-rated focus averaged {a['focus']}/10 {first}"
        txt += f", {b['focus']}/10 in the {b['days']} check-in days before." if b and b["focus"] is not None else "."
        out.append({"text": txt, "refs": [lst] + ([s["splitRef"]] if s["splitRef"] else [])})
    if a["sleepSelf"] is not None:
        txt = f"Self-reported sleep averaged {a['sleepSelf']} h {span}"
        txt += f", {b['sleepSelf']} h before." if b and b["sleepSelf"] is not None else "."
        out.append({"text": txt, "refs": [lst]})
    if a["restingHr"] is not None and refs["rhr"]:
        txt = f"Wearable resting heart rate averaged {a['restingHr']:g} bpm {span}"
        txt += f", {b['restingHr']:g} bpm before." if b and b["restingHr"] is not None else "."
        out.append({"text": txt, "refs": [refs["rhr"]]})
    n = a["days"]
    if n:
        med = s["med"]
        out.append({"text": f"Medicine {span}: at the usual time on {med.get('on_time', 0)}, later on {med.get('late', 0)}, "
                            f"not taken on {med.get('missed', 0)} of {n} check-in days.", "refs": [lst]})
        side = ", ".join(f"{SIDE[k]} {_pct(v, n)}" for k, v in s["side"].most_common()) or "none reported"
        out.append({"text": f"Reported in check-ins {span}: reduced appetite or skipped meal {_pct(s['appetiteReduced'], n)}; {side}.",
                    "refs": [lst]})
        if s["focusLost"]:
            w, c = s["focusLost"].most_common(1)[0]
            trig = ", ".join(f"{TRIGGER[k]} ({v})" for k, v in s["triggers"].most_common(3))
            out.append({"text": f"Focus most often lost in the {WHEN[w]} ({_pct(c, n)}). Most frequent triggers: {trig or 'none reported'}.",
                        "refs": [lst]})
    return out


def consistency_facts(t: dict | None, answers: dict[str, str], qr_ref: str | None, profile_meds: list[dict]) -> list[dict]:
    """Where sources disagree. Neutral wording: a prompt for the conversation, not a judgement."""
    out: list[dict] = []
    if t:
        s, refs, lst = t["summary"], t["refs"], t["refs"]["list"]
        a, b = s["after"], s["before"]
        span = f"since {fmt_date(s['split'])}" if s["split"] else f"since {fmt_date(t['since'])}"
        if a["sleepSelf"] is not None and a["sleepDevice"] is not None and abs(a["sleepSelf"] - a["sleepDevice"]) >= 0.5 and refs["sleep"]:
            out.append({"text": f"Sleep {span}: check-ins average {a['sleepSelf']} h; the wearable recorded {a['sleepDevice']} h on the same nights.",
                        "refs": [lst, refs["sleep"]]})
        se = answers.get("side_effects", "")
        if qr_ref and se and "none" in se.lower():
            parts = []
            if s["side"].get("racing_heart"):
                parts.append(f"racing heart on {s['side']['racing_heart']} days in check-ins")
            if b and a["restingHr"] is not None and b["restingHr"] is not None and a["restingHr"] - b["restingHr"] >= 5:
                parts.append(f"wearable resting heart rate {b['restingHr']:g} → {a['restingHr']:g} bpm")
            if s["appetiteReduced"]:
                parts.append(f"reduced appetite on {s['appetiteReduced']} check-in days")
            if parts:
                out.append({"text": f"Pre-visit chat: \"None of these\" for side effects. Other sources {span}: " + "; ".join(parts) + ".",
                            "refs": [qr_ref, lst] + ([refs["rhr"]] if refs["rhr"] and "wearable" in " ".join(parts) else [])})
        adh = answers.get("med_adherence", "")
        missed, late = s["med"].get("missed", 0), s["med"].get("late", 0)
        if qr_ref and adh.lower().startswith("every day") and (missed or late):
            out.append({"text": f"Pre-visit chat: medicine taken \"every day\". Check-ins {span}: {missed} days not taken, {late} days later than usual.",
                        "refs": [qr_ref, lst]})
    # Medicines the patient reports outside the clinic that the chat answers don't mention.
    if qr_ref and answers:
        said = " ".join(answers.values()).lower()
        for m in profile_meds:
            if m["source"] == "patient" and m["status"] == "current" and "sleep" in (m.get("reason") or "").lower() \
                    and ("sleep" in said or "asleep" in said) and m["name"].lower() not in said:
                out.append({"text": f"Profile lists {m['name']} ({m['dose']}) for sleep; not mentioned in the pre-visit chat.",
                            "refs": [m["reference"], qr_ref]})
    return out
