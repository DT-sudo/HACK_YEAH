"""Access control and documentation rules."""


def test_patient_id_comes_from_token(client, login):
    A = login("anna")
    me = client.get("/me", headers=A).json()
    assert me["id"] == "anna-k"
    s = client.post("/me/intakes", headers=login("piotr"), json={"lang": "en"}).json()
    assert client.get(f"/me/intakes/{s['id']}", headers=A).status_code == 404


def test_roles_and_assignments(client, login):
    A, D = login("anna"), login("ewa")
    assert client.get("/doctor/patients", headers=A).status_code == 403
    assert client.get("/me/profile", headers=D).status_code == 403
    assert client.get("/doctor/patients/jan-k/sources/Condition/c-j-01", headers=D).status_code == 403
    assert client.get("/doctor/patients", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_break_glass_requires_reason_and_is_audited(client, login):
    D = login("ewa")
    assert client.post("/doctor/break-glass/jan-k", headers=D, json={"reason": "x"}).status_code == 422
    r = client.post("/doctor/break-glass/jan-k", headers=D, json={"reason": "Covering for Dr. Mazur, patient called in"})
    assert r.status_code == 200 and r.json()["breakGlass"]
    assert client.get("/doctor/patients/jan-k/sources/Condition/c-j-01", headers=D).status_code == 200
    audit = client.get("/doctor/audit", headers=D).json()
    assert any(a["action"] == "break_glass" and a["reason"] for a in audit)


def test_profile_delete_vs_documentation(client, login):
    A = login("anna")
    assert client.delete("/me/profile/medications/ms-a02", headers=A).status_code == 200  # not yet documented
    piotr = login("piotr")  # Piotr's profile entries were used in his confirmed intake
    r = client.delete("/me/profile/medications/ms-p01", headers=piotr)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "documented"
    r = client.patch("/me/profile/medications/ms-p01", headers=piotr, json={"current": False})
    assert r.status_code == 200
    med = next(m for m in r.json()["medications"] if m["id"] == "ms-p01")
    assert med["current"] is False
    r = client.delete("/me/profile/lifestyle/occupation", headers=piotr)
    assert r.status_code == 409
    r = client.put("/me/profile/lifestyle/occupation", headers=piotr, json={"value": "Office job now"})
    assert r.status_code == 200
    D = login("ewa")
    b = client.get("/doctor/patients/piotr-n/briefs/brief-p-1005", headers=D).json()
    assert any(f["text"].startswith("Work: Office job now") and not f["stale"] for f in b["lifestyle"])
    assert any(m["reference"] == "MedicationStatement/ms-p01" and m["status"] == "past" for m in b["medications"])


def test_wearable_import_rejects_location(client, login):
    A = login("anna")
    assert client.put("/me/profile/wearable", headers=A, json={"restingHr": 64, "gps": [50.0, 19.9]}).status_code == 422
    assert client.put("/me/profile/wearable", headers=A, json={"restingHr": 64, "stepsPerDay": 7000}).status_code == 200


def test_confirm_requires_truthful(client, login):
    from tests.conftest import run_intake
    A = login("anna")
    s = run_intake(client, A, {"complaint": "dry cough for 3 weeks"})
    assert client.post(f"/me/intakes/{s['id']}/confirm", headers=A, json={"truthful": False}).status_code == 422
    assert client.post(f"/me/intakes/{s['id']}/confirm", headers=A, json={"truthful": True}).status_code == 200
    assert client.delete(f"/me/intakes/{s['id']}", headers=A).status_code == 409


def test_reconcile_records_provenance(client, login):
    D = login("ewa")
    r = client.post("/doctor/patients/piotr-n/medications/MedicationStatement/ms-p02/reconcile", headers=D)
    assert r.status_code == 200
    b = client.get("/doctor/patients/piotr-n/briefs/brief-p-1005", headers=D).json()
    row = next(m for m in b["medications"] if m["reference"] == "MedicationStatement/ms-p02")
    assert row["reconciled"]["by"] == "Dr. Ewa Wiśniewska"


def test_llm_log_has_no_content(client, login):
    from tests.conftest import run_intake
    A, D = login("anna"), login("ewa")
    run_intake(client, A, {"complaint": "secret-marker cough"})
    calls = client.get("/doctor/llm-calls", headers=D).text
    assert "secret-marker" not in calls and "t1_intake" in calls
