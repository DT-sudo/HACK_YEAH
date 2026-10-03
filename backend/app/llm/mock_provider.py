"""Deterministic provider. Implements T1-T3 with rules so the full flow runs offline, and doubles as
the safe fallback when a real model is unavailable or keeps failing validation.

It returns plain dicts shaped exactly like the JSON schemas, and goes through the same validation
as a real model's output.
"""
from __future__ import annotations

import re
from datetime import date

from app.llm.framework import CATEGORIES, GENERAL, Category, norm, slot_by_id, extract_from_text


def _lc(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def _fmt(d: str | None) -> str:
    if not d:
        return ""
    from app.fhir.describe import fmt_date
    return fmt_date(d)


def _partial(d: str) -> date:
    parts = [int(x) for x in d[:10].split("-")] + [1, 1]
    return date(parts[0], parts[1], parts[2])


def _answers_map(answers: list[dict]) -> dict[str, str]:
    return {a["slot"]: a["value"] for a in answers}


def _split_multi(v: str) -> list[str]:
    return [x.strip() for x in re.split(r";|,(?![^()]*\))", v) if x.strip()]


class MockProvider:
    name = "mock"
    model = "rules-v1"

    def run(self, task: str, system: str, payload: dict, schema: dict) -> tuple[dict, dict]:
        fn = {"t1_intake": self.t1, "t2_summary": self.t2, "t3_brief": self.t3}[task]
        return fn(payload), {"input_tokens": None, "output_tokens": None}

    # ------------------------------------------------------------------ T1
    def t1(self, p: dict) -> dict:
        cat: Category = CATEGORIES.get(p.get("category") or "general", GENERAL)
        lang = p.get("lang", "en")
        q = p.get("current_question") or {}
        msg = (p.get("latest_message") or {}).get("text", "")
        answered = {a["slot"] for a in p.get("answers", [])}
        extracted: list[dict] = []

        slot_id = q.get("slot")
        if slot_id == "complaint":
            extracted.append({"slot": "complaint", "label": "Reason for visit", "value": msg.strip()})
            for s, v in extract_from_text(cat.id, msg):
                sl = slot_by_id(cat.id, s)
                if sl and s not in answered:
                    extracted.append({"slot": s, "label": sl.label, "value": v})
        elif slot_id:
            sl = slot_by_id(cat.id, slot_id)
            if sl:
                value = self._canonical_value(cat, sl, msg)
                extracted.append({"slot": sl.id, "label": sl.label, "value": value})

        all_answers = _answers_map(p.get("answers", [])) | {e["slot"]: e["value"] for e in extracted}

        # Internal working list: initialise from context, then drop what the answers contradict.
        hyps = {h["label"]: h["status"] for h in p.get("working_hypotheses", [])}
        if not hyps:
            hyps = {h.id: "open" for h in cat.hypotheses if h.applies(p.get("context_pack", {}))}
        for rule in cat.rules:
            if rule.slot in all_answers and rule.hyp in hyps:
                v = all_answers[rule.slot]
                vv = _split_multi(v) if slot_by_id(cat.id, rule.slot) and slot_by_id(cat.id, rule.slot).type == "multi" else v
                if rule.test(vv):
                    hyps[rule.hyp] = rule.status
        open_h = {k for k, s in hyps.items() if s == "open"}

        nxt = None
        if p.get("question_count", 0) < p.get("question_limit", 12):
            remaining = [s for s in cat.slots if s.id not in all_answers]
            scored = [(sum(1 for h in s.discriminates if h in open_h), i, s) for i, s in enumerate(remaining)]
            useful = [t for t in scored if t[0] > 0]
            if useful:
                nxt = max(useful, key=lambda t: (t[0], -t[1]))[2]
            else:
                nxt = next((s for s in remaining if s.core), None)

        return {
            "extracted_answers": extracted,
            "working_hypotheses": [{"label": k, "status": v} for k, v in hyps.items()],
            "next_question": None if nxt is None else {
                "slot": nxt.id, "text": nxt.text(lang), "answer_type": nxt.type, "options": nxt.option_labels(lang)},
            "stop": nxt is None,
        }

    @staticmethod
    def _canonical_value(cat: Category, sl, msg: str) -> str:
        if sl.type == "scale":
            m = re.search(r"\d+", msg)
            return str(max(0, min(10, int(m.group())))) if m else msg.strip()
        if sl.type == "multi":
            return ", ".join(sl.canonical(x) for x in _split_multi(msg))
        if sl.type == "single":
            v = sl.canonical(msg)
            if v not in [o.en for o in sl.options]:
                hit = dict(extract_from_text(cat.id, msg)).get(sl.id)
                if hit:
                    return hit
            return v
        return msg.strip()

    # ------------------------------------------------------------------ T2
    SUGGESTED = {
        "respiratory": (["What should I keep an eye on while the cough lasts?", "Should I change anything before my next visit?", "Do I need any tests?"],
                        ["Na co zwracać uwagę, dopóki trwa kaszel?", "Czy powinienem/powinnam coś zmienić przed kolejną wizytą?", "Czy potrzebuję jakichś badań?"]),
        "musculoskeletal": (["Can I keep training, and how much?", "What should I keep an eye on?", "Do I need any tests?"],
                            ["Czy mogę dalej trenować i ile?", "Na co zwracać uwagę?", "Czy potrzebuję jakichś badań?"]),
        "_": (["What should I keep an eye on?", "Should I change anything before my next visit?", "Do I need any tests?"],
              ["Na co zwracać uwagę?", "Czy powinienem/powinnam coś zmienić przed kolejną wizytą?", "Czy potrzebuję jakichś badań?"]),
    }
    LABEL_PL = {"onset": "Początek", "character": "Charakter", "timing": "Pora dnia", "assoc": "Inne objawy",
                "sob": "Brak tchu", "changes": "Zmiany przed początkiem", "severity": "Uciążliwość (0–10)",
                "location": "Miejsce", "mechanism": "Jak się zaczęło", "aggravating": "Co nasila",
                "swelling": "Obrzęk, blokowanie, niestabilność", "activity_change": "Zmiana aktywności",
                "relief": "Co pomaga", "triggers": "Co wywołuje", "painkillers": "Leki przeciwbólowe"}

    def t2(self, p: dict) -> dict:
        cat = p.get("category") or "general"
        lang = p.get("lang", "en")
        a = _answers_map(p.get("answers", []))
        meds = p.get("reported_medicines", [])
        paras: list[str] = []
        if lang == "pl":
            for slot, value in a.items():
                if slot == "complaint":
                    continue
                sl = slot_by_id(cat, slot)
                v = value
                if sl and sl.options:
                    v = ", ".join(next((o.pl for o in sl.options if o.en == x), x) for x in _split_multi(value))
                paras.append(f"{self.LABEL_PL.get(slot, sl.label if sl else slot)}: {_lc(v)}.")
            bring = ["Opakowania wszystkich przyjmowanych leków" + (f", w tym: {', '.join(meds)}" if meds else ""),
                     "Wyniki badań wykonanych poza tą przychodnią"]
            sq = self.SUGGESTED.get(cat, self.SUGGESTED["_"])[1]
        else:
            paras = self._en_sentences(cat, a)
            bring = ["The packaging of every medicine you take" + (f", including {', '.join(meds)}" if meds else ""),
                     "Results of any tests done outside this clinic"]
            sq = self.SUGGESTED.get(cat, self.SUGGESTED["_"])[0]
        return {"summary_text": paras, "bring_items": bring, "suggested_questions": sq}

    @staticmethod
    def _en_sentences(cat: str, a: dict[str, str]) -> list[str]:
        out: list[str] = []
        s1 = []
        if "onset" in a:
            s1.append(f"It started {_lc(a['onset'])}.")
        if cat == "respiratory" and "character" in a:
            s1.append("The cough is dry." if a["character"] == "Dry" else f"You cough up {_lc(a['character'])}.")
        elif "character" in a:
            s1.append(f"You describe it as {_lc(a['character'])}.")
        if "location" in a:
            s1.append(f"Where: {_lc(a['location'])}.")
        if "mechanism" in a:
            m = a["mechanism"]
            s1.append(f"It {_lc(m)}." if m.startswith("Came") else f"It started {_lc(m)}.")
        if "timing" in a:
            t = a["timing"]
            s1.append("It has no clear pattern during the day." if t == "No pattern" else
                      f"It's worse {_lc(t)}." if t in ("At night", "In the morning", "After physical effort", "Later in the day") else
                      f"Timing: {_lc(t)}.")
        if s1:
            out.append(" ".join(s1))
        s2 = []
        if "assoc" in a:
            items = [x for x in _split_multi(a["assoc"]) if x != "None of these"]
            s2.append(f"You also have: {', '.join(_lc(x) for x in items)}." if items else "You haven't noticed other symptoms.")
        if "sob" in a:
            s2.append("You don't get out of breath." if a["sob"] == "No" else f"You get out of breath: {_lc(a['sob'])}.")
        if "aggravating" in a:
            s2.append(f"It gets worse with: {', '.join(_lc(x) for x in _split_multi(a['aggravating']))}.")
        if "swelling" in a:
            items = [x for x in _split_multi(a["swelling"]) if x != "None of these"]
            s2.append(f"You noticed: {', '.join(_lc(x) for x in items)}." if items else "No swelling, locking or giving way.")
        if s2:
            out.append(" ".join(s2))
        s3 = []
        for slot, lead in (("changes", "Before it started"), ("activity_change", "Before it started"), ("relief", "What helps"),
                           ("triggers", "What brings it on"), ("painkillers", "Painkillers")):
            if slot in a:
                s3.append(f"{lead}: {_lc(a[slot])}.")
        if "severity" in a:
            s3.append(f"You rated it at {a['severity']} out of 10.")
        if s3:
            out.append(" ".join(s3))
        known = {"complaint", "onset", "character", "location", "mechanism", "timing", "assoc", "sob", "aggravating",
                 "swelling", "changes", "activity_change", "relief", "triggers", "painkillers", "severity"}
        out += [f"{k.replace('_', ' ').capitalize()}: {v}." for k, v in a.items() if k not in known]
        return out

    # ------------------------------------------------------------------ T3
    def t3(self, p: dict) -> dict:
        pack = p["context_pack"]
        cat = pack.get("complaint_category", "general")
        recs = pack.get("records", [])
        intake = next((r for r in recs if r["kind"] == "intake"), None)
        q = intake["ref"] if intake else None
        a = {x["slot"]: x["value"] for x in (intake or {}).get("details", {}).get("answers", [])}
        text = norm(" ".join(a.values()))
        onset = _lc(a.get("onset", "not stated"))
        by_ref = {r["ref"]: r for r in recs}
        conns: list[dict] = []
        cited_reasons: set[str] = set()

        meds = [r for r in recs if r["kind"] in ("clinic_prescription", "reported_medication")
                and r["details"].get("status") in ("active", "intended")]
        chk = next((r for r in recs if r["kind"] == "checkins"), None)
        cd = (chk or {}).get("details", {})
        n_days = ((cd.get("after") or {}).get("days")) or 0
        chk_counts = {"appetite": cd.get("appetite_reduced_days", 0), "insomnia": cd.get("side_effect_days", {}).get("insomnia", 0),
                      "palpitations": cd.get("side_effect_days", {}).get("racing_heart", 0),
                      "tachycardia": cd.get("side_effect_days", {}).get("racing_heart", 0),
                      "headache": cd.get("side_effect_days", {}).get("headache", 0),
                      "irritability": cd.get("side_effect_days", {}).get("irritability", 0),
                      "dry mouth": cd.get("side_effect_days", {}).get("dry_mouth", 0)}
        for m in meds:
            d = m["details"]
            who = "this clinic" if m["kind"] == "clinic_prescription" else ("another provider" if d.get("from_other_provider") else "patient-reported")
            effects = d.get("registry_effects") or [{"term": t, "freq": "common", "aliases": []} for t in d.get("product_info_side_effects", [])]
            matched = []
            for e in effects:
                if e["freq"] not in ("very common", "common"):
                    continue
                in_chat = all(w in text for w in norm(e["term"]).split()) or any(norm(al) in text for al in e.get("aliases", []))
                key = next((k for k in chk_counts if k in e["term"]), None)
                days = chk_counts.get(key, 0) if key and chk else 0
                if (in_chat or days) and not any(x["term"] in ("palpitations", "tachycardia") and e["term"] in ("palpitations", "tachycardia") for x in matched):
                    matched.append({**e, "in_chat": in_chat, "days": days})
            if matched:
                start = d.get("start")
                weeks = ""
                if start:
                    delta = (date.fromisoformat(pack["today"]) - _partial(start)).days // 7
                    weeks = f" ({delta} weeks before this visit)" if delta < 52 else ""
                src = "" if m["kind"] == "clinic_prescription" else f" ({who})"
                if len(matched) == 1:
                    listed = f"lists {matched[0]['term']} as a {matched[0]['freq']} side effect"
                else:
                    parts = [f"{x['term']} ({x['freq']})" for x in matched]
                    listed = f"lists {', '.join(parts[:-1])} and {parts[-1]} among undesirable effects"
                reported = []
                for x in matched:
                    where = (["pre-visit chat"] if x["in_chat"] else []) + ([f"{x['days']} of {n_days} check-in days"] if x["days"] else [])
                    reported.append(f"{x['term']} ({'; '.join(where)})" if chk else x["term"])
                onset_txt = f", onset {onset}" if a.get("onset") else ""
                refs = [m["ref"]] + ([d["registry_ref"]] if d.get("registry_ref") else [])
                refs += ([q] if q and any(x["in_chat"] for x in matched) else []) + ([chk["ref"]] if chk and any(x["days"] for x in matched) else [])
                registry = " (URPL registry)" if d.get("registry_ref") else ""
                conns.append({"statement": f"{m['title']}{src} started {_fmt(start) or 'date not given'}{weeks}. "
                                           f"Its product information{registry} {listed}. "
                                           f"Patient reports {', '.join(reported)}{onset_txt}.",
                              "refs": refs})
                if d.get("reason_ref"):
                    cited_reasons.add(d["reason_ref"])
            for sym in d.get("used_for", []):
                if all(w in text for w in norm(sym).split()):
                    since = f" since {_fmt(d['start'])}" if d.get("start") else ""
                    conns.append({"statement": f"Patient reports {sym} and takes {d['name']} {d.get('dose', '')}".rstrip()
                                               + f"{since}, {'prescribed by another provider' if d.get('from_other_provider') else 'self-reported'}.",
                                  "refs": [m["ref"]] + ([q] if q else [])})
            for loinc in d.get("lab_watch", []):
                lab = next((r for r in recs if r["kind"] == "lab" and r["details"].get("loinc") == {"creatinine": "2160-0"}.get(loinc, loinc)), None)
                if lab:
                    ld = lab["details"]
                    rng = "outside" if ld.get("abnormal") else "within"
                    conns.append({"statement": f"{d['name']} {d.get('dose', '')}, {who}. Last {ld['name'].lower()} {ld['value']} {ld['unit']} "
                                               f"on {_fmt(lab['date'])} ({ld.get('months_ago', '?')} months ago), {rng} the reference range.",
                                  "refs": [m["ref"], lab["ref"]]})

        for ref in sorted(cited_reasons):
            c = by_ref.get(ref)
            med = next((m for m in meds if m["details"].get("reason_ref") == ref), None)
            if c and med:
                conns.append({"statement": f"{c['details']['name']} recorded {_fmt(c['date'])}; reason {med['details']['name']} was started.",
                              "refs": [ref]})

        for r in recs:
            d = r["details"]
            if r["kind"] == "wearable" and d.get("series"):
                s = d["series"]
                first, last = s[0]["value"], s[-1]["value"]
                if first and last >= first * 1.5:
                    conns.append({"statement": f"Weekly {d['metric']} rose from {first:g} {d['unit']} to {last:g} {d['unit']} over "
                                               f"{len(s) - 1} weeks (wearable). Patient reports onset {onset}.",
                                  "refs": [r["ref"]] + ([q] if q else [])})
            elif r["kind"] == "encounter":
                lead = "Earlier visit" if cat == "adhd_followup" else "Earlier episode"
                conns.append({"statement": f"{lead}: {d['reason']}." + (f" {d['outcome']}." if d.get("outcome") else ""),
                              "refs": [r["ref"]]})
            elif r["kind"] == "vital":
                conns.append({"statement": f"{d['name']}: {d['value']} {d['unit']} on {_fmt(r['date'])} (most recent on record).",
                              "refs": [r["ref"]]})
            elif r["kind"] == "document":
                conns.append({"statement": f"{d['type']}: {d['finding']}", "refs": [r["ref"]]})
            elif r["kind"] == "lab" and d.get("abnormal"):
                conns.append({"statement": f"{d['name']}: {d['value']} {d['unit']} on {_fmt(r['date'])}, outside the reference range "
                                           f"({d.get('range_low')}–{d.get('range_high')}).", "refs": [r["ref"]]})
            elif r["kind"] == "allergy" and cat == "respiratory":
                conns.append({"statement": f"Allergy recorded: {d['substance']}, {d['reaction']}.", "refs": [r["ref"]]})

        openq: list[str] = []  # missing indications and stale profile data are added live by the brief service
        if cat == "respiratory":
            openq.append("Exposure at home or work (dust, mould, new environment) not covered in the intake.")
            if a.get("sob") and a["sob"] != "No":
                openq.append(f"Breathlessness reported ({_lc(a['sob'])}); timing relative to the cough not established.")
        if cat == "musculoskeletal":
            openq.append("Footwear, running surface or training plan not covered in the intake.")
        if cat == "adhd_followup":
            wo = a.get("wear_off", "")
            if wo in ("Before lunch", "Early afternoon", "Late afternoon"):
                openq.append(f"Effect reported to fade {_lc(wo)}; time of the morning dose not covered in the intake.")
            if a.get("caffeine") == "More than before":
                openq.append("Caffeine intake reported as higher than before; amount and timing not covered.")
            if a.get("mood") in ("Mostly low", "Anxious or on edge", "Up and down"):
                openq.append(f"Mood most days reported as \"{_lc(a['mood'])}\"; not explored further in the intake.")
            if "appetite" in text or cd.get("appetite_reduced_days"):
                openq.append("Body weight since the dose change not recorded.")
            if a.get("wishes"):
                openq.append(f"Patient would like to discuss: \"{a['wishes']}\"")
        if a.get("changes") == "Started a new medicine":
            openq.append("Patient reports starting a new medicine before onset but did not name it in the chat.")

        return {"chief_complaint": self._chief(cat, a, cd), "connections": conns, "open_questions": openq}

    @staticmethod
    def _chief(cat: str, a: dict[str, str], checkins: dict | None = None) -> str:
        if cat == "adhd_followup":
            c = checkins or {}
            head = (f"ADHD follow-up after the change to {c['split_label']} on {_fmt(c['split_date'])}" if c.get("split_label")
                    else "ADHD follow-up")
            parts = []
            if a.get("overall"):
                parts.append(f"overall {_lc(a['overall'])}")
            if a.get("wear_off"):
                parts.append(f"effect fades: {_lc(a['wear_off'])}")
            if a.get("work_impact"):
                parts.append(f"impact on work/study {a['work_impact']}/10")
            return head + (". " + "; ".join(parts)[:1].upper() + "; ".join(parts)[1:] + "." if parts else ".")
        sev = f" Impact {a['severity']}/10." if "severity" in a else ""
        onset = f"onset {_lc(a['onset'])}" if "onset" in a else "onset not stated"
        if cat == "respiratory":
            ch = a.get("character", "")
            head = "Dry cough" if ch == "Dry" else (f"Cough with {_lc(ch)}" if ch else "Cough")
            t = a.get("timing")
            timing = "" if not t else (", no daily pattern" if t == "No pattern" else f", worse {_lc(t)}")
            return f"{head}, {onset}{timing}.{sev}"
        if cat == "musculoskeletal":
            c = norm(a.get("complaint", ""))
            side = "Right " if re.search(r"\bright\b|\bpraw", c) else "Left " if re.search(r"\bleft\b|\blew", c) else ""
            part = next((en for rx, en in ((r"knee|kolan", "knee"), (r"back|plec", "back"), (r"shoulder|bark", "shoulder"),
                                            (r"ankle|kostk", "ankle"), (r"hip|biodr", "hip")) if re.search(rx, c)), "joint")
            loc = f" ({_lc(a['location'])})" if a.get("location") else ""
            mech = f", {_lc(a['mechanism'])}" if a.get("mechanism") else ""
            worse = f" Worse with {', '.join(_lc(x) for x in _split_multi(a['aggravating']))}." if a.get("aggravating") else ""
            sev = f" Impact {a['severity']}/10 at its worst." if "severity" in a else ""
            out = f"{side}{part} pain{loc}, {onset}{mech}.{worse}{sev}"
            return out[:1].upper() + out[1:]
        if cat == "headache":
            ch = f", {_lc(a['character'])}" if a.get("character") else ""
            loc = f", {_lc(a['location'])}" if a.get("location") else ""
            return f"Headache{ch}{loc}, {onset}.{sev}"
        loc = f" Location: {a['location']}." if a.get("location") else ""
        ch = f" Described as {_lc(a['character'])}." if a.get("character") else ""
        return f"Presenting complaint in the patient's words (quoted below), {onset}.{loc}{ch}{sev}"
