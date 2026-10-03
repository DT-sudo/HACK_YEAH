"""Golden cases: synthetic patients with expected relevant connections, all with valid citations."""
from tests.conftest import run_intake


def _brief(client, D, pid):
    bid = next(p for p in client.get("/doctor/patients", headers=D).json()["patients"] if p["patientId"] == pid)["briefId"]
    return client.get(f"/doctor/patients/{pid}/briefs/{bid}", headers=D).json()


def test_anna_dry_cough(client, login):
    A, D = login("anna"), login("ewa")
    s = run_intake(client, A, {"complaint": "I've had a dry cough for about three weeks and it's worse at night",
                               "assoc": "Heartburn", "sob": "No", "changes": "Started a new medicine", "severity": "5"})
    client.post(f"/me/intakes/{s['id']}/confirm", headers=A, json={"truthful": True})
    b = _brief(client, D, "anna-k")
    assert b["chiefComplaint"]["text"].startswith("Dry cough, onset about 3 weeks ago, worse at night")
    hist = {f["text"]: [c["reference"] for c in f["citations"]] for f in b["relevantHistory"]}
    lis = next(t for t in hist if t.startswith("Lisinopril"))
    assert "dry cough" in lis and "MedicationRequest/mr-4471" in hist[lis]
    assert any("Encounter/enc-1874" in r for r in hist.values())
    assert any("DocumentReference/doc-552" in r for r in hist.values())
    assert any("omeprazole" in t.lower() for t in hist)
    assert any("Work record last updated 10 months ago" in q for q in b["openQuestions"])
    # data minimisation: unrelated skin check and lipid panel are not in the context
    assert not any("Encounter/enc-0911" in r for r in hist.values())
    assert b["generation"]["context_records"] < b["generation"]["total_records"]
    srcs = {m["reference"]: m["source"] for m in b["medications"]}
    assert srcs["MedicationRequest/mr-4471"] == "clinic" and srcs["MedicationStatement/ms-a03"] == "patient"


def test_piotr_seeded_brief(client, login):
    D = login("ewa")
    b = _brief(client, D, "piotr-n")
    assert b["chiefComplaint"]["text"].startswith("Right knee pain")
    texts = " ".join(f["text"] for f in b["relevantHistory"])
    assert "14 km to 38 km" in texts and "creatinine 0.98" in texts and "ankle sprain" in texts
    assert any(f["stale"] for f in b["lifestyle"])


def test_every_citation_resolves(client, login):
    D = login("ewa")
    b = _brief(client, D, "piotr-n")
    for f in b["relevantHistory"] + b["lifestyle"] + [b["chiefComplaint"]]:
        for c in f["citations"]:
            r = client.get(f"/doctor/patients/piotr-n/sources/{c['reference']}", headers=D)
            assert r.status_code == 200 and r.json()["verified"], c


def test_polish_intake(client, login):
    A = login("anna")
    s = client.post("/me/intakes", headers=A, json={"lang": "pl"}).json()
    assert s["messages"][0]["text"].startswith("Dzień dobry")
    s = client.post(f"/me/intakes/{s['id']}/messages", headers=A, json={"text": "Mam suchy kaszel od trzech tygodni, gorzej w nocy"}).json()
    assert s["question"]["options"] and s["question"]["text"].startswith("Czy")
