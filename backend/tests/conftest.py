import os

os.environ.setdefault("VC_DATABASE_URL", "sqlite:///:memory:")
os.environ["VC_LLM_PROVIDER"] = "mock"  # evals run offline and deterministically

import pytest
from fastapi.testclient import TestClient

from app.main import app, reset_demo


@pytest.fixture()
def client():
    with TestClient(app) as c:
        reset_demo()
        yield c


@pytest.fixture()
def login(client):
    def _login(user: str) -> dict:
        r = client.post("/auth/login", json={"username": user})
        assert r.status_code == 200
        return {"Authorization": f"Bearer {r.json()['token']}"}
    return _login


def run_intake(client, headers, answers: dict, lang="en", default_first=True):
    s = client.post("/me/intakes", headers=headers, json={"lang": lang}).json()
    while s.get("question"):
        q = s["question"]
        a = answers.get(q["slot"], q["options"][0] if (default_first and q["options"]) else "5")
        s = client.post(f"/me/intakes/{s['id']}/messages", headers=headers, json={"text": a, "mode": "choice"}).json()
    return s
