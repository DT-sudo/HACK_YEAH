"""Diagnostic leakage + hidden hypotheses: nothing diagnostic reaches patient or doctor."""
from app.llm.framework import CATEGORIES
from app.llm.validation import has_diagnostic_wording, question_hints_disease
from tests.conftest import run_intake

HYPOTHESIS_IDS = {h.id for c in CATEGORIES.values() for h in c.hypotheses}


def test_language_filter_catches_conclusions():
    for bad in ["Likely ACE-inhibitor cough.", "Findings consistent with reflux", "Risk of kidney injury",
                "Recommend stopping lisinopril", "Cough due to lisinopril", "You have asthma", "Rule out pneumonia",
                "Prawdopodobnie refluks", "Zalecam odstawienie leku"]:
        assert has_diagnostic_wording(bad), bad
    for ok in ["Lisinopril 10 mg started 14 Aug 2026. Its product information lists dry cough as a common side effect.",
               "Omeprazole (patient-reported, another provider): indication not given.",
               "Earlier episode: cough after URTI, resolved within 10 days."]:
        assert not has_diagnostic_wording(ok), ok


def test_framework_questions_never_hint_at_disease():
    for cat in CATEGORIES.values():
        for slot in cat.slots:
            for lang in ("en", "pl"):
                assert not question_hints_disease(slot.text(lang), []), slot.text(lang)
                for o in slot.option_labels(lang):
                    assert not question_hints_disease(o, []), o


def test_hypotheses_never_in_any_response(client, login):
    A, D = login("anna"), login("ewa")
    seen = []
    s = client.post("/me/intakes", headers=A, json={"lang": "en"}).json()
    while s.get("question"):
        seen.append(str(s))
        q = s["question"]
        r = client.post(f"/me/intakes/{s['id']}/messages", headers=A,
                        json={"text": "dry cough for 3 weeks" if q["slot"] == "complaint" else (q["options"] or ["4"])[0]})
        s = r.json()
        seen.append(r.text)
    seen.append(client.get(f"/me/intakes/{s['id']}/summary", headers=A).text)
    s = client.post(f"/me/intakes/{s['id']}/confirm", headers=A, json={"truthful": True}).json()
    day = client.get("/doctor/patients", headers=D).json()
    bid = next(p for p in day["patients"] if p["patientId"] == "anna-k")["briefId"]
    seen.append(client.get(f"/doctor/patients/anna-k/briefs/{bid}", headers=D).text)
    blob = "\n".join(seen)
    assert "working_hypotheses" not in blob and "hypothes" not in blob.lower()
    for h in HYPOTHESIS_IDS:
        assert f'"{h}"' not in blob, h


def test_brief_has_no_diagnostic_wording(client, login):
    A, D = login("anna"), login("ewa")
    run_intake(client, A, {"complaint": "I've had a dry cough for about three weeks and it's worse at night",
                           "assoc": "Heartburn", "sob": "No", "changes": "Started a new medicine", "severity": "5"})
    sid = client.post("/me/intakes", headers=A, json={"lang": "en"}).json()["id"]
    client.post(f"/me/intakes/{sid}/confirm", headers=A, json={"truthful": True})
    bid = next(p for p in client.get("/doctor/patients", headers=D).json()["patients"] if p["patientId"] == "anna-k")["briefId"]
    b = client.get(f"/doctor/patients/anna-k/briefs/{bid}", headers=D).json()
    texts = [b["chiefComplaint"]["text"]] + [f["text"] for f in b["relevantHistory"]] + b["openQuestions"]
    for t in texts:
        assert not has_diagnostic_wording(t), t
