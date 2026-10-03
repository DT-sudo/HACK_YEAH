"""Red-flag cases, including paraphrases and Polish (with and without diacritics)."""
import pytest

from app.services import safety

POSITIVE = [
    "I have chest pain", "Pain in my chest since this morning", "my chest feels tight", "crushing chest pressure",
    "I can't breathe properly", "struggling to breathe when lying down", "I fainted at work", "I passed out yesterday",
    "her lips are blue", "my face is drooping on one side", "slurred speech since an hour", "throat is closing",
    "worst headache of my life", "I want to kill myself",
    "Mam ból w klatce piersiowej", "bol w klatce od rana", "ucisk w klatce", "duszę się", "dusze sie", "nie mogę oddychać",
    "zemdlałam w sklepie", "nie chcę żyć", "najgorszy ból głowy w życiu",
]
NEGATIVE = [
    "I've had a dry cough for a few weeks", "My right knee hurts at the front when I run", "headaches most mornings",
    "Only on stairs or when hurrying", "Mam suchy kaszel od trzech tygodni", "boli mnie kolano", "heartburn after dinner",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_red_flag_detected(text):
    assert safety.check_text(text) is not None, text


@pytest.mark.parametrize("text", NEGATIVE)
def test_no_false_alarm(text):
    assert safety.check_text(text) is None, text


def test_tapped_answer_in_context():
    assert safety.check_answer_in_context("Do you get out of breath?", "Yes, even when resting")
    assert safety.check_answer_in_context("Czy brakuje Panu/Pani tchu?", "Tak, nawet w spoczynku")
    assert not safety.check_answer_in_context("Do you get out of breath?", "Only on stairs or when hurrying")


def test_structured_scale_trigger():
    assert safety.check_structured("scale", "9", "pain across my chest and arm")
    assert not safety.check_structured("scale", "9", "my knee hurts")


def test_emergency_stops_intake_and_flags_clinic(client, login):
    A, D = login("anna"), login("ewa")
    s = client.post("/me/intakes", headers=A, json={"lang": "en"}).json()
    s = client.post(f"/me/intakes/{s['id']}/messages", headers=A, json={"text": "sudden chest pain and sweating"}).json()
    assert s["state"] == "EMERGENCY" and s["emergency"] and s["question"] is None
    r = client.post(f"/me/intakes/{s['id']}/messages", headers=A, json={"text": "hello?"})
    assert r.status_code == 409
    day = client.get("/doctor/patients", headers=D).json()["patients"]
    anna = next(p for p in day if p["patientId"] == "anna-k")
    assert anna["status"] == "urgent" and day[0]["status"] == "urgent"
    me = client.get("/me", headers=A).json()
    assert me["upcoming"]["preparation"] == "urgent"
