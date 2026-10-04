"""ADHD follow-up: daily check-ins, trends, registry citations and the consistency check."""


def _brief(client, D, pid):
    bid = next(p for p in client.get("/doctor/patients", headers=D).json()["patients"] if p["patientId"] == pid)["briefId"]
    return client.get(f"/doctor/patients/{pid}/briefs/{bid}", headers=D).json()


ANSWERS = {"med_taken": "on_time", "focus": 7, "focus_lost": ["late_afternoon"], "triggers": ["meetings"],
           "sleep": "6.5", "appetite": "lower", "side_effects": ["insomnia"]}


def test_checkin_flow_updates_trends(client, login):
    N, M = login("natalia"), login("marta")
    st = client.get("/me/checkins?lang=pl", headers=N).json()
    assert st["enabled"] and not st["todayDone"] and st["questionnaire"]["items"][0]["text"].startswith("Czy")
    before = len([d for d in st["followUp"]["series"] if d["ref"]])
    st = client.post("/me/checkins", headers=N, json={"lang": "en", "answers": ANSWERS}).json()
    assert st["todayDone"] and len([d for d in st["followUp"]["series"] if d["ref"]]) == before + 1
    # same day again updates instead of duplicating
    st = client.post("/me/checkins", headers=N, json={"lang": "en", "answers": {**ANSWERS, "focus": 8}}).json()
    assert len([d for d in st["followUp"]["series"] if d["ref"]]) == before + 1
    t = client.get("/doctor/patients/natalia-z/trends", headers=M).json()
    assert t["followUp"]["series"][-1]["focus"] == 8 and t["followUp"]["split"] == "2026-09-17"


def test_checkin_validation_and_red_flag(client, login):
    N, M = login("natalia"), login("marta")
    assert client.post("/me/checkins", headers=N, json={"answers": {**ANSWERS, "focus": 11}}).status_code == 422
    assert client.post("/me/checkins", headers=N, json={"answers": {**ANSWERS, "sleep": "9"}}).status_code == 422
    r = client.post("/me/checkins", headers=N, json={"answers": {**ANSWERS, "note": "ból w klatce od rana"}}).json()
    assert r["emergency"] == "chest_pain"
    day = client.get("/doctor/patients", headers=M).json()["patients"]
    assert next(p for p in day if p["patientId"] == "natalia-z")["status"] == "urgent"


def test_no_plan_no_checkins(client, login):
    assert client.get("/me/checkins", headers=login("anna")).json()["enabled"] is False
    assert client.post("/me/checkins", headers=login("anna"), json={"answers": ANSWERS}).status_code == 404


def test_seeded_followup_brief(client, login):
    M = login("marta")
    b = _brief(client, M, "bartosz-k")
    hist = {f["text"]: [c["reference"] for c in f["citations"]] for f in b["relevantHistory"]}
    mph = next(t for t in hist if t.startswith("Methylphenidate"))
    assert "URPL" in mph and "DocumentReference/urpl-methylphenidate" in hist[mph]
    srcs = {c["reference"]: c["source"] for f in b["relevantHistory"] for c in f["citations"]}
    assert srcs["DocumentReference/urpl-methylphenidate"] == "registry"
    assert b["trends"] and b["followUp"]["series"]
    cons = " ".join(f["text"] for f in b["consistency"])
    assert '"every day"' in cons and "not taken" in cons
    r = client.get("/doctor/patients/bartosz-k/sources/DocumentReference/urpl-methylphenidate", headers=M)
    assert r.status_code == 200 and r.json()["source"] == "registry"
    # registry data is shared reference data, not a backdoor to other patients' records
    assert client.get("/doctor/patients/bartosz-k/sources/QuestionnaireResponse/chk-natalia-z-2026-09-08", headers=M).status_code == 404


def test_live_followup_intake_and_consistency(client, login):
    N, M = login("natalia"), login("marta")
    s = client.post("/me/intakes", headers=N, json={"lang": "en"}).json()
    assert "follow-up" in s["messages"][0]["text"]
    answers = {"complaint": "Focus is much better, but it wears off in the afternoon and I sleep badly",
               "med_adherence": "Every day", "side_effects": "None of these", "work_impact": "4", "wishes": "Afternoons"}
    while s["question"]:
        q = s["question"]
        s = client.post(f"/me/intakes/{s['id']}/messages", headers=N,
                        json={"text": answers.get(q["slot"], (q["options"] or ["x"])[0])}).json()
    client.post(f"/me/intakes/{s['id']}/confirm", headers=N, json={"truthful": True})
    b = _brief(client, M, "natalia-z")
    assert b["chiefComplaint"]["text"].startswith("ADHD follow-up after the change to Methylphenidate ER 27 mg")
    cons = [f["text"] for f in b["consistency"]]
    assert any("wearable recorded" in c for c in cons)  # self-reported vs device sleep
    assert any('"None of these"' in c and "racing heart" in c for c in cons)
    assert any("Melatonin" in c for c in cons)
    for f in b["consistency"]:
        assert len(f["sources"]) >= 1 and f["citations"]
    # the model only ever saw aggregates: no free-text check-in notes in the context pack
    from app.fhir.client import get_fhir
    from app.services.context import build_context_pack
    pack = str(build_context_pack(get_fhir(), "natalia-z", "adhd_followup").pack)
    assert "Coffee at 4 pm" not in pack and "Natalia" not in pack and "93061100000" not in pack
